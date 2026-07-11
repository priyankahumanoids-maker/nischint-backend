// Predictive Alerts Screen
import { useState, useEffect, useCallback } from 'react';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity,
  RefreshControl, ActivityIndicator, Alert, Linking, Switch,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import * as Location from 'expo-location';
import { predictiveAlertService } from '@/services/endpoints';
import { colors, spacing, fontSize, radius, shadows, riskColor } from '@/theme';
import { useAuthStore } from '@/stores/authStore';

// Fallback check points (used only if GPS is denied / unavailable).
// Center of India so the map is reasonably centered regardless of region.
const FALLBACK_POINTS = [
  { name: 'Area (GPS unavailable)', lat: 20.5937, lng: 78.9629, speed: 0, heading: 0 },
];

type CheckPoint = { name: string; lat: number; lng: number; speed: number; heading: number };

// Build 4 monitored points around the user's current location:
//   1. Current Area   — exact GPS
//   2. 1 km North
//   3. 1 km East
//   4. 1 km South-West
// 0.009° ≈ 1 km in latitude. Longitude is scaled by cos(lat) for accuracy.
function buildCheckPointsAround(lat: number, lng: number): CheckPoint[] {
  const dLat = 0.009;
  const dLng = 0.009 / Math.max(0.2, Math.cos((lat * Math.PI) / 180));
  return [
    { name: 'Current Area',    lat,               lng,               speed: 0,  heading: 0 },
    { name: '1 km North',      lat: lat + dLat,   lng,               speed: 0,  heading: 0 },
    { name: '1 km East',       lat,               lng: lng + dLng,   speed: 0,  heading: 90 },
    { name: '1 km South-West', lat: lat - dLat,   lng: lng - dLng,   speed: 0,  heading: 225 },
  ];
}

export default function AlertsScreen() {
  const { profileMode } = useAuthStore();
  if (profileMode === 'women' || profileMode === 'senior') {
    return <WomanProtectionScreen />;
  }
  if (['kids', 'family'].includes(profileMode)) {
    return <ChildProtectionScreen />;
  }
  return <ReferenceAlertsScreen />;
}

function ChildProtectionScreen() {
  const [checkedIn, setCheckedIn] = useState(false);
  const statusItems = [
    ['sparkles-outline', 'AI', '#DCFCE7', '#16A34A'],
    ['location', 'Location', '#DCFCE7', '#16A34A'],
    ['mic-outline', 'Mic', '#FDE8E8', '#EF4444'],
    ['watch-outline', 'Wearable', '#DCFCE7', '#16A34A'],
    ['bar-chart', 'Network', '#FEF3C7', '#F59E0B'],
  ];
  const monitoring = [
    ['hardware-chip-outline', 'AI Safety Monitoring', 'Smart threat detection by NISCHINT AI', 'ON', '#DBEAFE'],
    ['location-outline', 'Location Monitoring', 'Live GPS shared with your guardians', 'ON', '#DCFCE7'],
    ['mic-outline', 'Microphone Detection', 'Disabled by you', 'OFF', '#F1F5F9'],
    ['navigate-outline', 'Route Monitoring', 'Home -> School route tracked', 'ON', '#DBEAFE'],
    ['shield-outline', 'Background Protection', 'App-level safety running in background', 'ON', '#DCFCE7'],
    ['pulse-outline', 'Safe Walk', 'Activates when you start walking alone', 'Standby', '#FEF3C7'],
    ['flash-outline', 'Crash Detection', 'Detects sudden impact events', 'ON', '#DBEAFE'],
    ['warning-outline', 'Fall Detection', 'Detects if you trip or fall', 'ON', '#DCFCE7'],
  ];
  const devices = [
    ['watch-outline', "Aarav's Watch", 'Apple Watch', 'Connected', '72%', 'SOS: ON'],
    ['key-outline', 'Emergency Keychain', 'BLE Keychain', 'Connected', '88%', ''],
  ];

  return (
    <SafeAreaView style={childProtection.safe} edges={['top']}>
      <ScrollView style={childProtection.scroll} contentContainerStyle={childProtection.content} showsVerticalScrollIndicator={false}>
        <View style={childProtection.hero}>
          <Text style={childProtection.eyebrow}>NISCHINT</Text>
          <View style={childProtection.heroRow}>
            <Text style={childProtection.title}>My Protection</Text>
            <View style={childProtection.protectedPill}>
              <View style={childProtection.pillDot} />
              <Text style={childProtection.pillText}>Protected</Text>
            </View>
          </View>
        </View>

        <Text style={childProtection.sectionLabel}>LIVE STATUS</Text>
        <View style={childProtection.statusRow}>
          {statusItems.map(([icon, label, bg, color]) => (
            <View key={label} style={[childProtection.statusTile, { backgroundColor: bg }]}>
              <Ionicons name={icon as keyof typeof Ionicons.glyphMap} size={25} color={color} />
              <Text style={[childProtection.statusLabel, { color }]}>{label}</Text>
              <View style={[childProtection.statusDot, { backgroundColor: color }]} />
            </View>
          ))}
        </View>

        <Text style={childProtection.sectionLabel}>MONITORING</Text>
        <View style={childProtection.card}>
          {monitoring.map(([icon, title, desc, state, bg], index) => (
            <View key={title} style={[childProtection.monitorRow, index > 0 && childProtection.rowBorder]}>
              <View style={[childProtection.monitorIcon, { backgroundColor: bg }]}>
                <Ionicons name={icon as keyof typeof Ionicons.glyphMap} size={24} color={state === 'OFF' ? '#94A3B8' : '#0EA5E9'} />
              </View>
              <View style={childProtection.monitorCopy}>
                <Text style={childProtection.monitorTitle}>{title}</Text>
                <Text style={childProtection.monitorDesc} numberOfLines={1}>{desc}</Text>
              </View>
              <Text style={[
                childProtection.statePill,
                state === 'OFF' ? childProtection.stateOff : state === 'Standby' ? childProtection.stateStandby : childProtection.stateOn,
              ]}>{state}</Text>
            </View>
          ))}
        </View>

        <View style={childProtection.notice}>
          <Ionicons name="shield-outline" size={20} color="#007AFF" />
          <Text style={childProtection.noticeText}>Your guardian manages these settings. <Text style={childProtection.noticeLink}>Contact Parent to change.</Text></Text>
        </View>

        <Text style={childProtection.sectionLabel}>SAFETY CHECK</Text>
        <View style={childProtection.checkCard}>
          <View style={childProtection.checkRow}>
            <View>
              <Text style={childProtection.checkTitle}>Last Safety Check</Text>
              <Text style={childProtection.checkOk}>✓ Today 08:15 AM</Text>
            </View>
            <View>
              <Text style={childProtection.nextLabel}>Next check</Text>
              <Text style={childProtection.nextTime}>6:00 PM today</Text>
            </View>
          </View>
          <TouchableOpacity
            activeOpacity={0.86}
            onPress={() => setCheckedIn(true)}
            style={[childProtection.imSafeButton, checkedIn && childProtection.checkedInButton]}
          >
            <Text style={[childProtection.imSafeText, checkedIn && childProtection.checkedInText]}>{checkedIn ? '⊙  Checked In ✓' : "I'm Safe ✅"}</Text>
          </TouchableOpacity>
        </View>

        <Text style={childProtection.sectionLabel}>CONNECTED DEVICES</Text>
        {devices.map(([icon, title, desc, status, battery, sos]) => (
          <View key={title} style={childProtection.deviceCard}>
            <View style={childProtection.deviceIcon}>
              <Ionicons name={icon as keyof typeof Ionicons.glyphMap} size={30} color="#6366F1" />
            </View>
            <View style={childProtection.deviceCopy}>
              <Text style={childProtection.deviceTitle}>{title}</Text>
              <Text style={childProtection.deviceDesc}>{desc}</Text>
              <Text style={childProtection.deviceMeta}>● {status}  ▱ {battery} {sos ? `   ${sos}` : ''}</Text>
            </View>
          </View>
        ))}
        <View style={childProtection.addDevice}>
          <Ionicons name="add" size={30} color="#94A3B8" />
          <View>
            <Text style={childProtection.addDeviceTitle}>Add Device</Text>
            <Text style={childProtection.addDeviceSub}>Ask your guardian to pair a new device</Text>
          </View>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

function WomanProtectionScreen() {
  const { profileMode } = useAuthStore();
  const isSeniorMode = profileMode === 'senior';
  const [segment, setSegment] = useState<'Monitoring' | 'Devices' | 'Permissions'>('Monitoring');
  const monitoring = [
    ['hardware-chip-outline', 'AI Monitoring', 'Active - Threat detection on', '#EAF5FF', '#0EA5E9', true],
    ['location-outline', 'Location Monitoring', 'Active - High accuracy', '#EAFBF1', '#22C55E', true],
    ['mic-outline', 'Microphone Monitoring', 'Active - Distress detection', '#F6F0FF', '#A855F7', true],
    ['navigate-outline', 'Route Monitoring', 'Active - Safe route tracking', '#ECFEFF', '#06B6D4', true],
    ['paper-plane-outline', 'Safe Walk Monitoring', 'Standby - Start safe walk to use', '#FFF7ED', '#F59E0B', false],
    ['battery-half-outline', 'Battery Monitoring', '87% - Good health', '#ECFDF5', '#22C55E', true],
    ['wifi-outline', 'Offline Detection', 'Active - Guardian alert on loss', '#FFF1F2', '#EF4444', true],
    ['pulse-outline', 'Crash Detection', 'Active - Impact sensors on', '#FFF7ED', '#F97316', true],
    ['analytics-outline', 'Fall Detection', 'Active - Gyroscope monitoring', '#FFF7ED', '#F97316', true],
    ['checkmark-circle-outline', 'Safety Check', 'Next: 6:00 PM today', '#EAFBF1', '#22C55E', true],
  ];
  const aiStatus = [
    ['hardware-chip-outline', 'AI Monitoring'],
    ['location-outline', 'Location Monitoring'],
    ['map-outline', 'Route Monitoring'],
    ['alarm-outline', 'Emergency Detection'],
    ['shield-outline', 'Background Protection'],
    ['mic-outline', 'Microphone Detection'],
  ];
  const devices = [
    { icon: 'watch-outline', title: 'Smart Watch', status: 'Connected', battery: '72%', sync: 'Last sync: 2 min ago', actions: ['SOS Trigger', 'Location Sharing'], connected: true },
    { icon: 'key-outline', title: 'Smart Safety Keychain', status: 'Connected', battery: '88%', sync: 'Last sync: Just now', actions: ['Emergency Alert', 'Guardian Alerts'], connected: true },
    { icon: 'ellipse-outline', title: 'Smart Band', status: 'Not Connected', battery: '', sync: '', actions: [], connected: false, button: '+ Pair Device' },
    { icon: 'radio-outline', title: 'GPS Tracker', status: 'Not Connected', battery: '', sync: '', actions: [], connected: false, button: '+ Add Device' },
  ];
  const deviceTabItems = [
    { icon: 'watch-outline', title: 'Apple Watch', type: 'Smart Watch', status: 'Connected', battery: '72%', signal: 4, sos: 'ON', sync: 'Last sync: 2 min ago', muted: false },
    { icon: 'fitness-outline', title: 'Mi Band 8', type: 'Smart Band', status: 'Connected', battery: '45%', signal: 3, sos: 'ON', sync: 'Last sync: 5 min ago', muted: false },
    { icon: 'ellipse-outline', title: 'Oura Ring', type: 'Smart Ring', status: 'Offline', battery: '91%', signal: 0, sos: 'OFF', sync: 'Last sync: 2h ago', muted: true },
    { icon: 'key-outline', title: 'SOS Keychain', type: 'Emergency Keychain', status: 'Connected', battery: '88%', signal: 4, sos: 'ON', sync: 'Last sync: Just now', muted: false },
    { icon: 'radio-outline', title: 'GPS Tracker', type: 'GPS Tracker', status: 'Connected', battery: '60%', signal: 2, sos: 'OFF', sync: 'Last sync: 1 min ago', muted: false },
  ];

  return (
    <SafeAreaView style={womanProtection.safe} edges={['top']}>
      <View style={womanProtection.header}>
        <TouchableOpacity activeOpacity={0.82} style={womanProtection.backBtn}>
          <Ionicons name="chevron-back" size={24} color="#0F172A" />
        </TouchableOpacity>
        <View style={womanProtection.headerCenter}>
          <Text style={womanProtection.userName}>{isSeniorMode ? 'ncfdhhj' : 'swaesrgh'}</Text>
          <View style={womanProtection.roleRow}>
            <View style={womanProtection.onlineDot} />
            <Text style={[womanProtection.roleText, isSeniorMode && womanProtection.seniorRoleText]}>{isSeniorMode ? 'Senior Citizen - Protected' : 'Woman - Protected'}</Text>
          </View>
        </View>
        <View style={[womanProtection.rolePill, isSeniorMode && womanProtection.seniorRolePill]}>
          <Text style={[womanProtection.rolePillText, isSeniorMode && womanProtection.seniorRolePillText]}>{isSeniorMode ? 'Senior' : 'Woman'}</Text>
        </View>
      </View>

      <View style={womanProtection.titleBlock}>
        <Text style={womanProtection.title}>Protection Status</Text>
        <Text style={womanProtection.subtitle}>All monitoring systems active</Text>
      </View>

      <View style={womanProtection.segmentWrap}>
        {(['Monitoring', 'Devices', 'Permissions'] as const).map((item) => (
          <TouchableOpacity
            key={item}
            activeOpacity={0.84}
            onPress={() => setSegment(item)}
            style={[womanProtection.segmentItem, segment === item && womanProtection.segmentActive]}
          >
            <Text style={segment === item ? womanProtection.segmentActiveText : womanProtection.segmentText}>{item}</Text>
          </TouchableOpacity>
        ))}
      </View>

      <ScrollView style={womanProtection.scroll} contentContainerStyle={womanProtection.content} showsVerticalScrollIndicator={false}>
        {segment === 'Devices' ? (
          <>
            <View style={womanProtection.sectionRow}>
              <Text style={womanProtection.sectionLabel}>CONNECTED DEVICES</Text>
              <Text style={womanProtection.addLink}>+ Add Device</Text>
            </View>
            {deviceTabItems.map((device) => (
              <View key={device.title} style={[womanProtection.wearableCard, device.muted && womanProtection.mutedCard]}>
                <View style={womanProtection.wearableTop}>
                  <Ionicons name={device.icon as keyof typeof Ionicons.glyphMap} size={31} color={device.muted ? '#B8C3D4' : '#6366F1'} />
                  <View style={womanProtection.wearableCopy}>
                    <Text style={[womanProtection.wearableTitle, device.muted && womanProtection.mutedText]}>{device.title}</Text>
                    <Text style={womanProtection.wearableType}>{device.type}</Text>
                  </View>
                  <View style={womanProtection.connectedRow}>
                    <View style={[womanProtection.miniDot, { backgroundColor: device.muted ? '#DCE4EF' : '#22C55E' }]} />
                    <Text style={[womanProtection.connectedText, device.muted && womanProtection.offlineText]}>{device.status}</Text>
                  </View>
                </View>
                <View style={womanProtection.metricsRow}>
                  <View style={womanProtection.metricBox}>
                    <Text style={[womanProtection.metricValue, device.muted && womanProtection.mutedText]}>{device.battery}</Text>
                    <Text style={womanProtection.metricLabel}>Battery</Text>
                  </View>
                  <View style={womanProtection.metricBox}>
                    <View style={womanProtection.signalBars}>
                      {[1, 2, 3, 4].map((bar) => (
                        <View key={bar} style={[womanProtection.signalBar, { height: 6 + bar * 3, backgroundColor: bar <= device.signal ? '#22C55E' : '#E2E8F0' }]} />
                      ))}
                    </View>
                    <Text style={womanProtection.metricLabel}>Signal</Text>
                  </View>
                  <View style={womanProtection.metricBox}>
                    <Text style={[womanProtection.metricValue, device.sos === 'ON' ? womanProtection.onText : womanProtection.offText]}>{device.sos}</Text>
                    <Text style={womanProtection.metricLabel}>SOS</Text>
                  </View>
                </View>
                <Text style={womanProtection.syncText}>{device.sync}</Text>
              </View>
            ))}
            <TouchableOpacity activeOpacity={0.82} style={womanProtection.addWearable}>
              <Ionicons name="watch-outline" size={42} color="#6366F1" />
              <Text style={womanProtection.addWearableTitle}>Add Wearable Device</Text>
              <Text style={womanProtection.addWearableSub}>Smart watch, band, ring, or emergency keychain</Text>
              <Text style={womanProtection.addWearableLink}>+ Pair Device</Text>
            </TouchableOpacity>
          </>
        ) : (
          <>
            <Text style={womanProtection.sectionLabel}>MONITORING & PROTECTION</Text>
            {monitoring.map(([icon, title, desc, bg, color, active]) => (
              <View key={title as string} style={womanProtection.monitorCard}>
                <View style={[womanProtection.monitorIcon, { backgroundColor: bg as string }]}>
                  <Ionicons name={icon as keyof typeof Ionicons.glyphMap} size={24} color={color as string} />
                </View>
                <View style={womanProtection.monitorCopy}>
                  <Text style={womanProtection.monitorTitle}>{title}</Text>
                  <Text style={womanProtection.monitorDesc}>{desc}</Text>
                </View>
                <View style={[womanProtection.cardDot, { backgroundColor: active ? '#22C55E' : '#D8E0EA' }]} />
              </View>
            ))}

            <Text style={womanProtection.sectionLabel}>AI PROTECTION STATUS</Text>
            <View style={womanProtection.statusCard}>
              {aiStatus.map(([icon, title], index) => (
                <View key={title} style={[womanProtection.statusRow, index > 0 && womanProtection.rowBorder]}>
                  <View style={womanProtection.statusIcon}>
                    <Ionicons name={icon as keyof typeof Ionicons.glyphMap} size={22} color="#0EA5E9" />
                  </View>
                  <Text style={womanProtection.statusTitle}>{title}</Text>
                  <View style={womanProtection.activePill}>
                    <Text style={womanProtection.activePillText}>Active</Text>
                  </View>
                  {title === 'Microphone Detection' ? (
                    <Switch value trackColor={{ false: '#DCE4EF', true: '#22C55E' }} thumbColor="#FFFFFF" />
                  ) : null}
                </View>
              ))}
            </View>

            <Text style={womanProtection.sectionLabel}>CONNECTED DEVICES</Text>
            {devices.map((device) => (
              <View key={device.title} style={womanProtection.deviceCard}>
                <View style={womanProtection.deviceTop}>
                  <Ionicons name={device.icon as keyof typeof Ionicons.glyphMap} size={30} color={device.connected ? '#6366F1' : '#A6B2C3'} />
                  <View style={womanProtection.deviceCopy}>
                    <Text style={womanProtection.deviceTitle}>{device.title}</Text>
                    <View style={womanProtection.deviceStatusRow}>
                      <View style={[womanProtection.miniDot, { backgroundColor: device.connected ? '#22C55E' : '#CBD5E1' }]} />
                      <Text style={[womanProtection.deviceStatus, !device.connected && womanProtection.deviceStatusOff]}>{device.status}</Text>
                    </View>
                  </View>
                </View>

                {device.connected ? (
                  <>
                    <View style={womanProtection.batteryRow}>
                      <Text style={womanProtection.deviceMeta}>Battery</Text>
                      <Text style={womanProtection.batteryText}>{device.battery}</Text>
                    </View>
                    <View style={womanProtection.track}>
                      <View style={[womanProtection.fill, { width: device.battery as any }]} />
                    </View>
                    <Text style={womanProtection.syncText}>{device.sync}</Text>
                    {device.actions.map((action) => (
                      <View key={action} style={womanProtection.deviceActionRow}>
                        <Text style={womanProtection.deviceActionText}>{action}</Text>
                        <Switch value trackColor={{ false: '#DCE4EF', true: '#22C55E' }} thumbColor="#FFFFFF" />
                      </View>
                    ))}
                  </>
                ) : (
                  <TouchableOpacity activeOpacity={0.82} style={womanProtection.outlineBtn}>
                    <Text style={womanProtection.outlineBtnText}>{device.button}</Text>
                  </TouchableOpacity>
                )}
              </View>
            ))}
            <TouchableOpacity activeOpacity={0.82} style={womanProtection.dashedAdd}>
              <Ionicons name="add" size={24} color="#64748B" />
              <Text style={womanProtection.dashedAddText}>Add Device</Text>
            </TouchableOpacity>
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

function ReferenceAlertsScreen() {
  const [filter, setFilter] = useState<'All' | 'Emergency' | 'Warning' | 'Info'>('All');
  const [statusTab, setStatusTab] = useState<'Active' | 'Resolved'>('Active');
  const alertCards = [
    {
      icon: 'medical-outline',
      tone: '#EF3442',
      bg: '#FFF1F3',
      type: 'Emergency',
      title: 'SOS Triggered - Aarav',
      body: 'Aarav has triggered an SOS alert. Immediate attention required.',
      time: '3:42 PM',
      place: 'Sector 12',
      primary: 'Escalate Now',
      secondary: 'Call Now',
    },
    {
      icon: 'warning-outline',
      tone: '#EF3442',
      bg: '#FFF1F3',
      type: 'Emergency',
      title: 'No Response Safety Check - Priya',
      body: 'Priya has not responded to the scheduled safety check.',
      time: '3:30 PM',
      place: 'MG Road',
      primary: 'Escalate Now',
      secondary: 'Call Now',
    },
    {
      icon: 'navigate-circle-outline',
      tone: '#F59E0B',
      bg: '#FFF9ED',
      type: 'Warning',
      title: 'GPS Disabled - Aarav',
      body: "Aarav's device GPS has been turned off. Location tracking paused.",
      time: '2:58 PM',
      place: 'Last seen: Sector 12',
      primary: 'View Location',
      secondary: 'Acknowledge',
    },
    {
      icon: 'map-outline',
      tone: '#F59E0B',
      bg: '#FFF9ED',
      type: 'Warning',
      title: 'Route Deviation - Aarav',
      body: 'Aarav deviated from the expected route home from school.',
      time: '2:15 PM',
      place: 'Sector 18',
      primary: 'View Location',
      secondary: 'Acknowledge',
    },
    {
      icon: 'battery-dead-outline',
      tone: '#FF6B22',
      bg: '#FFF4EE',
      type: 'Attention',
      title: 'Battery Critical 8% - Priya',
      body: "Priya's device battery is critically low. Device may go offline soon.",
      time: '1:44 PM',
      place: 'MG Road',
      primary: 'View Location',
      secondary: 'Acknowledge',
    },
    {
      icon: 'checkbox-outline',
      tone: '#0B9DFF',
      bg: '#EAF5FF',
      type: 'Info',
      title: 'Arrived at School - Aarav',
      body: 'Aarav has arrived at school safely.',
      time: '8:05 AM',
      place: 'DPS School',
      primary: 'View',
    },
    {
      icon: 'walk-outline',
      tone: '#0B9DFF',
      bg: '#EAF5FF',
      type: 'Info',
      title: 'Safe Walk Completed - Priya',
      body: 'Priya completed her morning safe walk without any issues.',
      time: '7:50 AM',
      place: 'Indiranagar',
      primary: 'View',
    },
    {
      icon: 'sunny-outline',
      tone: '#0B9DFF',
      bg: '#EAF5FF',
      type: 'Info',
      title: 'Morning Check-in',
      body: 'All family members completed their morning check-in.',
      time: '7:00 AM',
      place: '',
      primary: 'View',
    },
  ];
  const visibleAlerts = filter === 'All'
    ? alertCards
    : alertCards.filter((item) => item.type === filter || (filter === 'Warning' && item.type === 'Attention'));
  const resolvedAlerts = [
    { icon: 'checkbox', title: 'Priya arrived at school', time: 'Today - 8:42 AM', bg: '#EAFBF1', color: '#29C86A' },
    { icon: 'checkbox', title: 'Riya completed Safe Walk', time: 'Today - 9:18 AM', bg: '#EAFBF1', color: '#29C86A' },
    { icon: 'shield', title: 'AI Safety Check passed', time: 'Today - 7:00 AM', bg: '#EAF5FF', color: '#2196F3' },
    { icon: 'checkbox', title: 'Nana arrived at park safely', time: 'Today - 6:45 AM', bg: '#EAFBF1', color: '#29C86A' },
    { icon: 'checkbox', title: 'All members checked in overnight', time: 'Yesterday - 11:58 PM', bg: '#EAFBF1', color: '#29C86A' },
  ];

  const onPrimary = (item: any) => {
    if (item.primary === 'Escalate Now') Alert.alert('Escalation Started', `${item.title} has been escalated to emergency contacts.`);
    else Alert.alert(item.primary, item.title);
  };

  const onSecondary = (item: any) => {
    if (item.secondary === 'Call Now') Linking.openURL('tel:112').catch(() => {});
    else Alert.alert('Acknowledged', `${item.title} marked for guardian review.`);
  };

  return (
    <SafeAreaView style={refAlerts.safe} edges={['top']}>
      <ScrollView style={refAlerts.scroll} contentContainerStyle={refAlerts.content} showsVerticalScrollIndicator={false}>
        <View style={refAlerts.hero}>
          <View style={refAlerts.heroTitleRow}>
            <View>
              <Text style={refAlerts.eyebrow}>SAFETY UPDATES</Text>
              <Text style={refAlerts.title}>Alert Center</Text>
            </View>
            <View style={refAlerts.totalBadge}>
              <Text style={refAlerts.totalBadgeText}>8</Text>
            </View>
          </View>

          <View style={refAlerts.statRow}>
            <View style={[refAlerts.statCard, { borderColor: '#91283C', backgroundColor: '#3B1B33' }]}>
              <Text style={[refAlerts.statNum, { color: '#FF3A47' }]}>2</Text>
              <Text style={[refAlerts.statLabel, { color: '#FF3A47' }]}>Emergency</Text>
            </View>
            <View style={[refAlerts.statCard, { borderColor: '#806122', backgroundColor: '#424037' }]}>
              <Text style={[refAlerts.statNum, { color: '#F8A807' }]}>3</Text>
              <Text style={[refAlerts.statLabel, { color: '#F8A807' }]}>Warning</Text>
            </View>
            <View style={[refAlerts.statCard, { borderColor: '#20765A', backgroundColor: '#185458' }]}>
              <Text style={[refAlerts.statNum, { color: '#22D473' }]}>3</Text>
              <Text style={[refAlerts.statLabel, { color: '#22D473' }]}>Info</Text>
            </View>
          </View>

          <View style={refAlerts.onlineBanner}>
            <Ionicons name="checkmark-circle-outline" size={20} color="#25DF7D" />
            <Text style={refAlerts.onlineText}>Co-Guardian Sunita is online and monitoring</Text>
          </View>
        </View>

        <View style={refAlerts.body}>
          <View style={refAlerts.segment}>
            <TouchableOpacity
              activeOpacity={0.84}
              onPress={() => setStatusTab('Active')}
              style={[refAlerts.segmentItem, statusTab === 'Active' && refAlerts.segmentActive]}
            >
              <Text style={statusTab === 'Active' ? refAlerts.segmentActiveText : refAlerts.segmentInactiveText}>Active (8)</Text>
            </TouchableOpacity>
            <TouchableOpacity
              activeOpacity={0.84}
              onPress={() => setStatusTab('Resolved')}
              style={[refAlerts.segmentItem, statusTab === 'Resolved' && refAlerts.segmentActive]}
            >
              <Text style={statusTab === 'Resolved' ? refAlerts.segmentActiveText : refAlerts.segmentInactiveText}>Resolved</Text>
            </TouchableOpacity>
          </View>

          {statusTab === 'Active' ? (
            <View style={refAlerts.filterRow}>
              {(['All', 'Emergency', 'Warning', 'Info'] as const).map((item) => (
                <TouchableOpacity key={item} activeOpacity={0.82} onPress={() => setFilter(item)}>
                  <Text style={[refAlerts.filterChip, filter === item && refAlerts.filterChipActive]}>{item}</Text>
                </TouchableOpacity>
              ))}
            </View>
          ) : null}

          {statusTab === 'Resolved' ? resolvedAlerts.map((item) => (
            <View key={item.title} style={refAlerts.resolvedCard}>
              <View style={[refAlerts.resolvedIcon, { backgroundColor: item.bg }]}>
                <Ionicons name={item.icon as keyof typeof Ionicons.glyphMap} size={24} color={item.color} />
              </View>
              <View style={refAlerts.resolvedCopy}>
                <Text style={refAlerts.resolvedTitle}>{item.title}</Text>
                <Text style={refAlerts.resolvedTime}>{item.time}</Text>
              </View>
              <Ionicons name="checkmark-circle-outline" size={22} color="#22C55E" />
            </View>
          )) : visibleAlerts.map((item) => (
            <View key={item.title} style={[refAlerts.alertCard, { borderColor: item.tone, backgroundColor: item.bg }]}>
              <View style={refAlerts.alertTop}>
                <View style={[refAlerts.alertIcon, { backgroundColor: item.tone + '18' }]}>
                  <Ionicons name={item.icon as keyof typeof Ionicons.glyphMap} size={24} color={item.tone} />
                </View>
                <View style={refAlerts.alertCopy}>
                  <View style={refAlerts.alertTitleRow}>
                    <Text style={refAlerts.alertTitle}>{item.title}</Text>
                    <Text style={[refAlerts.priorityPill, { color: item.tone, borderColor: item.tone + '80' }]}>
                      {item.type}
                    </Text>
                    <TouchableOpacity activeOpacity={0.75} style={refAlerts.closePill}>
                      <Ionicons name="close" size={17} color="#7A8CA5" />
                    </TouchableOpacity>
                  </View>
                  <Text style={refAlerts.alertBody}>{item.body}</Text>
                  <View style={refAlerts.alertMetaRow}>
                    <Ionicons name="time-outline" size={15} color="#8EA0BB" />
                    <Text style={refAlerts.alertMeta}>{item.time}</Text>
                    {item.place ? <Ionicons name="location-outline" size={15} color="#8EA0BB" /> : null}
                    {item.place ? <Text style={refAlerts.alertMeta}>{item.place}</Text> : null}
                  </View>
                </View>
              </View>
              <View style={refAlerts.actionRow}>
                <TouchableOpacity
                  activeOpacity={0.85}
                  onPress={() => onPrimary(item)}
                  style={[refAlerts.actionBtn, item.type === 'Emergency' ? refAlerts.emergencyBtn : item.type === 'Info' ? refAlerts.infoBtn : refAlerts.warningBtn]}
                >
                  <Ionicons name={item.type === 'Emergency' ? 'flash' : item.primary === 'View' ? 'eye-outline' : 'location-outline'} size={16} color={item.type === 'Info' ? '#0B84FF' : '#FFFFFF'} />
                  <Text style={[refAlerts.actionText, item.type === 'Info' && refAlerts.infoActionText]}>{item.primary}</Text>
                </TouchableOpacity>
                {item.secondary ? (
                  <TouchableOpacity activeOpacity={0.85} onPress={() => onSecondary(item)} style={[refAlerts.actionBtn, refAlerts.secondaryBtn, item.type === 'Emergency' && refAlerts.callBtn]}>
                    <Ionicons name={item.secondary === 'Call Now' ? 'call-outline' : 'checkmark-outline'} size={16} color={item.type === 'Emergency' ? '#FFFFFF' : item.tone} />
                    <Text style={[refAlerts.actionText, item.type !== 'Emergency' && { color: item.tone }]}>{item.secondary}</Text>
                  </TouchableOpacity>
                ) : null}
              </View>
            </View>
          ))}
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const womanProtection = StyleSheet.create({
  safe: { flex: 1, backgroundColor: '#F3F7FB' },
  header: { height: 86, backgroundColor: '#FFFFFF', borderBottomWidth: 1, borderBottomColor: '#E2E8F0', flexDirection: 'row', alignItems: 'center', paddingHorizontal: 18 },
  backBtn: { width: 42, height: 42, borderRadius: 21, backgroundColor: '#F1F5F9', alignItems: 'center', justifyContent: 'center' },
  headerCenter: { flex: 1, alignItems: 'center' },
  userName: { color: '#020817', fontSize: 18, fontWeight: '900' },
  roleRow: { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 3 },
  onlineDot: { width: 7, height: 7, borderRadius: 4, backgroundColor: '#4ADE80' },
  roleText: { color: '#7C3AED', fontSize: 12, fontWeight: '900' },
  seniorRoleText: { color: '#92400E' },
  rolePill: { borderRadius: 16, paddingHorizontal: 13, paddingVertical: 7, backgroundColor: '#F4ECFF' },
  seniorRolePill: { backgroundColor: '#FEF3C7' },
  rolePillText: { color: '#7C3AED', fontSize: 12, fontWeight: '900' },
  seniorRolePillText: { color: '#92400E' },
  titleBlock: { backgroundColor: '#FFFFFF', paddingHorizontal: 18, paddingTop: 28, paddingBottom: 16 },
  title: { color: '#020817', fontSize: 24, fontWeight: '900' },
  subtitle: { color: '#53657E', fontSize: 15, marginTop: 5 },
  segmentWrap: { flexDirection: 'row', gap: 6, backgroundColor: '#FFFFFF', paddingHorizontal: 18, paddingBottom: 18, borderBottomWidth: 1, borderBottomColor: '#E2E8F0' },
  segmentItem: { flex: 1, height: 40, borderRadius: 20, backgroundColor: '#EEF3F9', alignItems: 'center', justifyContent: 'center' },
  segmentActive: { backgroundColor: '#10B7E7' },
  segmentText: { color: '#53657E', fontSize: 14, fontWeight: '900' },
  segmentActiveText: { color: '#FFFFFF', fontSize: 14, fontWeight: '900' },
  scroll: { flex: 1 },
  content: { paddingHorizontal: 18, paddingTop: 18, paddingBottom: 96 },
  sectionRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 },
  sectionLabel: { color: '#64748B', fontSize: 14, fontWeight: '900', letterSpacing: 1.3, marginTop: 10, marginBottom: 12 },
  addLink: { color: '#007AFF', fontSize: 13, fontWeight: '900' },
  monitorCard: { minHeight: 76, borderRadius: 16, backgroundColor: '#FFFFFF', flexDirection: 'row', alignItems: 'center', padding: 18, marginBottom: 14, shadowColor: '#0F172A', shadowOpacity: 0.05, shadowOffset: { width: 0, height: 6 }, shadowRadius: 14, elevation: 2 },
  monitorIcon: { width: 46, height: 46, borderRadius: 23, alignItems: 'center', justifyContent: 'center', marginRight: 14 },
  monitorCopy: { flex: 1 },
  monitorTitle: { color: '#06122A', fontSize: 17, fontWeight: '900' },
  monitorDesc: { color: '#53657E', fontSize: 14, marginTop: 3 },
  cardDot: { width: 10, height: 10, borderRadius: 5 },
  statusCard: { borderRadius: 16, backgroundColor: '#FFFFFF', overflow: 'hidden', marginBottom: 20, shadowColor: '#0F172A', shadowOpacity: 0.05, shadowOffset: { width: 0, height: 6 }, shadowRadius: 14, elevation: 2 },
  statusRow: { minHeight: 68, flexDirection: 'row', alignItems: 'center', paddingHorizontal: 18, gap: 12 },
  rowBorder: { borderTopWidth: 1, borderTopColor: '#EEF2F7' },
  statusIcon: { width: 40, height: 40, borderRadius: 20, backgroundColor: '#EAF5FF', alignItems: 'center', justifyContent: 'center' },
  statusTitle: { flex: 1, color: '#06122A', fontSize: 16, fontWeight: '900' },
  activePill: { borderRadius: 12, backgroundColor: '#DCFCE7', paddingHorizontal: 10, paddingVertical: 5 },
  activePillText: { color: '#16A34A', fontSize: 12, fontWeight: '900' },
  deviceCard: { borderRadius: 16, backgroundColor: '#FFFFFF', padding: 18, marginBottom: 14, shadowColor: '#0F172A', shadowOpacity: 0.05, shadowOffset: { width: 0, height: 6 }, shadowRadius: 14, elevation: 2 },
  deviceTop: { flexDirection: 'row', alignItems: 'center' },
  deviceCopy: { flex: 1, marginLeft: 12 },
  deviceTitle: { color: '#06122A', fontSize: 17, fontWeight: '900' },
  deviceStatusRow: { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 4 },
  miniDot: { width: 9, height: 9, borderRadius: 5 },
  deviceStatus: { color: '#16A34A', fontSize: 12, fontWeight: '800' },
  deviceStatusOff: { color: '#94A3B8' },
  batteryRow: { flexDirection: 'row', justifyContent: 'space-between', marginTop: 18 },
  deviceMeta: { color: '#64748B', fontSize: 13 },
  batteryText: { color: '#06122A', fontSize: 13, fontWeight: '900' },
  track: { height: 7, borderRadius: 4, backgroundColor: '#EEF2F7', marginTop: 7 },
  fill: { height: 7, borderRadius: 4, backgroundColor: '#22C55E' },
  syncText: { color: '#8EA0BB', fontSize: 12, marginTop: 12 },
  deviceActionRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginTop: 12 },
  deviceActionText: { color: '#42536B', fontSize: 15, fontWeight: '700' },
  outlineBtn: { height: 44, borderRadius: 22, borderWidth: 1.5, borderColor: '#008CFF', alignItems: 'center', justifyContent: 'center', marginTop: 18 },
  outlineBtnText: { color: '#008CFF', fontSize: 15, fontWeight: '900' },
  dashedAdd: { minHeight: 58, borderRadius: 16, borderWidth: 1.5, borderStyle: 'dashed', borderColor: '#CBD5E1', flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 10 },
  dashedAddText: { color: '#64748B', fontSize: 16, fontWeight: '900' },
  wearableCard: { borderRadius: 18, backgroundColor: '#FFFFFF', padding: 20, marginBottom: 16, shadowColor: '#0F172A', shadowOpacity: 0.05, shadowOffset: { width: 0, height: 6 }, shadowRadius: 14, elevation: 2 },
  mutedCard: { opacity: 0.58 },
  wearableTop: { flexDirection: 'row', alignItems: 'center' },
  wearableCopy: { flex: 1, marginLeft: 14 },
  wearableTitle: { color: '#06122A', fontSize: 18, fontWeight: '900' },
  mutedText: { color: '#64748B' },
  wearableType: { color: '#64748B', fontSize: 13, marginTop: 3 },
  connectedRow: { flexDirection: 'row', alignItems: 'center', gap: 7 },
  connectedText: { color: '#16A34A', fontSize: 12, fontWeight: '900' },
  offlineText: { color: '#94A3B8' },
  metricsRow: { flexDirection: 'row', gap: 10, marginTop: 18 },
  metricBox: { flex: 1, minHeight: 66, borderRadius: 14, backgroundColor: '#F8FAFC', alignItems: 'center', justifyContent: 'center' },
  metricValue: { color: '#06122A', fontSize: 20, fontWeight: '900' },
  metricLabel: { color: '#64748B', fontSize: 11, marginTop: 4 },
  signalBars: { height: 26, flexDirection: 'row', alignItems: 'flex-end', gap: 4 },
  signalBar: { width: 6, borderRadius: 3 },
  onText: { color: '#22C55E' },
  offText: { color: '#94A3B8' },
  addWearable: { minHeight: 190, borderRadius: 18, borderWidth: 1.5, borderStyle: 'dashed', borderColor: '#CBD5E1', alignItems: 'center', justifyContent: 'center', gap: 10 },
  addWearableTitle: { color: '#64748B', fontSize: 18, fontWeight: '900' },
  addWearableSub: { color: '#8EA0BB', fontSize: 14, textAlign: 'center' },
  addWearableLink: { color: '#007AFF', fontSize: 14, fontWeight: '900' },
});

const childProtection = StyleSheet.create({
  safe: { flex: 1, backgroundColor: '#F3F7FB' },
  scroll: { flex: 1 },
  content: { paddingBottom: 28 },
  hero: { backgroundColor: '#18345A', paddingHorizontal: 26, paddingTop: 64, paddingBottom: 34 },
  eyebrow: { color: '#A9B7CB', fontSize: 13, fontWeight: '800', letterSpacing: 1.5 },
  heroRow: { marginTop: 10, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 14 },
  title: { color: '#FFFFFF', fontSize: 30, fontWeight: '900' },
  protectedPill: { flexDirection: 'row', alignItems: 'center', gap: 7, paddingHorizontal: 13, height: 38, borderRadius: 19, backgroundColor: '#146B4B', borderWidth: 1, borderColor: '#22C55E66' },
  pillDot: { width: 12, height: 12, borderRadius: 6, backgroundColor: '#4ADE80' },
  pillText: { color: '#4ADE80', fontSize: 14, fontWeight: '900' },
  sectionLabel: { color: '#60708A', fontSize: 14, fontWeight: '900', letterSpacing: 1.7, marginTop: 22, marginBottom: 12, paddingHorizontal: 26 },
  statusRow: { flexDirection: 'row', gap: 10, paddingHorizontal: 26 },
  statusTile: { flex: 1, minHeight: 84, borderRadius: 18, alignItems: 'center', justifyContent: 'center', gap: 5 },
  statusLabel: { fontSize: 12, fontWeight: '900', textAlign: 'center' },
  statusDot: { width: 11, height: 11, borderRadius: 6 },
  card: { marginHorizontal: 26, borderRadius: 16, backgroundColor: '#FFFFFF', overflow: 'hidden', shadowColor: '#0F172A', shadowOpacity: 0.06, shadowOffset: { width: 0, height: 8 }, shadowRadius: 18, elevation: 2 },
  monitorRow: { minHeight: 80, flexDirection: 'row', alignItems: 'center', paddingHorizontal: 20, gap: 14 },
  rowBorder: { borderTopWidth: 1, borderTopColor: '#EEF2F7' },
  monitorIcon: { width: 46, height: 46, borderRadius: 23, alignItems: 'center', justifyContent: 'center' },
  monitorCopy: { flex: 1 },
  monitorTitle: { color: '#06122A', fontSize: 17, fontWeight: '900' },
  monitorDesc: { color: '#53657E', fontSize: 14, fontWeight: '600', marginTop: 3 },
  statePill: { minWidth: 48, textAlign: 'center', overflow: 'hidden', borderRadius: 15, paddingHorizontal: 8, paddingVertical: 7, fontSize: 13, fontWeight: '900' },
  stateOn: { color: '#0F5DEB', backgroundColor: '#DBEAFE' },
  stateOff: { color: '#64748B', backgroundColor: '#F1F5F9' },
  stateStandby: { color: '#A15C00', backgroundColor: '#FEF3C7' },
  notice: { marginHorizontal: 26, marginTop: 18, borderRadius: 16, borderWidth: 1, borderColor: '#B9DCFF', backgroundColor: '#EAF5FF', padding: 16, flexDirection: 'row', gap: 12 },
  noticeText: { flex: 1, color: '#007AFF', fontSize: 14, fontWeight: '700', lineHeight: 22 },
  noticeLink: { fontWeight: '900' },
  checkCard: { marginHorizontal: 26, borderRadius: 16, backgroundColor: '#FFFFFF', padding: 20, shadowColor: '#0F172A', shadowOpacity: 0.06, shadowOffset: { width: 0, height: 8 }, shadowRadius: 18, elevation: 2 },
  checkRow: { flexDirection: 'row', justifyContent: 'space-between', gap: 16 },
  checkTitle: { color: '#06122A', fontSize: 16, fontWeight: '900' },
  checkOk: { color: '#16A34A', fontSize: 14, fontWeight: '800', marginTop: 8 },
  nextLabel: { color: '#64748B', fontSize: 13, fontWeight: '700', textAlign: 'right' },
  nextTime: { color: '#F59E0B', fontSize: 14, fontWeight: '900', marginTop: 8, textAlign: 'right' },
  imSafeButton: { height: 56, borderRadius: 18, backgroundColor: '#20B956', alignItems: 'center', justifyContent: 'center', marginTop: 18 },
  checkedInButton: { backgroundColor: '#DCFCE7', borderWidth: 1, borderColor: '#86EFAC' },
  imSafeText: { color: '#FFFFFF', fontSize: 19, fontWeight: '900' },
  checkedInText: { color: '#15803D' },
  deviceCard: { marginHorizontal: 26, marginBottom: 12, minHeight: 114, borderRadius: 16, backgroundColor: '#FFFFFF', padding: 20, flexDirection: 'row', alignItems: 'center', gap: 16, shadowColor: '#0F172A', shadowOpacity: 0.06, shadowOffset: { width: 0, height: 8 }, shadowRadius: 18, elevation: 2 },
  deviceIcon: { width: 56, height: 56, borderRadius: 18, backgroundColor: '#F1F5F9', alignItems: 'center', justifyContent: 'center' },
  deviceCopy: { flex: 1 },
  deviceTitle: { color: '#06122A', fontSize: 17, fontWeight: '900' },
  deviceDesc: { color: '#64748B', fontSize: 14, fontWeight: '700', marginTop: 4 },
  deviceMeta: { color: '#0F9F54', fontSize: 12, fontWeight: '900', marginTop: 10 },
  addDevice: { marginHorizontal: 26, minHeight: 94, borderRadius: 16, borderWidth: 1.5, borderStyle: 'dashed', borderColor: '#B9CCE5', padding: 18, flexDirection: 'row', alignItems: 'center', gap: 18 },
  addDeviceTitle: { color: '#94A3B8', fontSize: 16, fontWeight: '900' },
  addDeviceSub: { color: '#CBD5E1', fontSize: 13, fontWeight: '700', marginTop: 4 },
});

const refAlerts = StyleSheet.create({
  safe: { flex: 1, backgroundColor: '#F5F7FB' },
  scroll: { flex: 1 },
  content: { paddingBottom: 18 },
  hero: { backgroundColor: '#132843', paddingHorizontal: 20, paddingTop: 72, paddingBottom: 20 },
  heroTitleRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  eyebrow: { color: '#A9BAD2', fontSize: 12, letterSpacing: 3, fontWeight: '800' },
  title: { color: '#FFFFFF', fontSize: 27, lineHeight: 34, fontWeight: '900', marginTop: 6 },
  totalBadge: { width: 36, height: 36, borderRadius: 18, alignItems: 'center', justifyContent: 'center', backgroundColor: '#EF3442' },
  totalBadgeText: { color: '#FFFFFF', fontSize: 16, fontWeight: '900' },
  statRow: { flexDirection: 'row', gap: 10, marginTop: 24 },
  statCard: { flex: 1, height: 76, borderRadius: 18, borderWidth: 1, alignItems: 'center', justifyContent: 'center' },
  statNum: { fontSize: 26, fontWeight: '900' },
  statLabel: { fontSize: 12, fontWeight: '800', marginTop: 5 },
  onlineBanner: { height: 40, borderRadius: 20, borderWidth: 1, borderColor: 'rgba(37,223,125,0.35)', backgroundColor: 'rgba(37,223,125,0.12)', flexDirection: 'row', alignItems: 'center', paddingHorizontal: 16, marginTop: 16 },
  onlineText: { color: '#FFFFFF', fontSize: 14, fontWeight: '800', marginLeft: 9 },
  body: { paddingHorizontal: 20, paddingTop: 20 },
  segment: { height: 56, borderRadius: 18, backgroundColor: '#FFFFFF', flexDirection: 'row', padding: 5, shadowColor: '#0F172A', shadowOpacity: 0.08, shadowOffset: { width: 0, height: 8 }, shadowRadius: 18, elevation: 3 },
  segmentItem: { flex: 1, borderRadius: 14, alignItems: 'center', justifyContent: 'center' },
  segmentActive: { flex: 1, borderRadius: 14, backgroundColor: '#08ADEC', alignItems: 'center', justifyContent: 'center' },
  segmentInactive: { flex: 1, borderRadius: 14, alignItems: 'center', justifyContent: 'center' },
  segmentActiveText: { color: '#FFFFFF', fontSize: 16, fontWeight: '900' },
  segmentInactiveText: { color: '#66738A', fontSize: 16, fontWeight: '900' },
  resolvedCard: { minHeight: 76, borderRadius: 18, backgroundColor: '#FFFFFF', marginTop: 14, paddingHorizontal: 18, flexDirection: 'row', alignItems: 'center', shadowColor: '#0F172A', shadowOpacity: 0.05, shadowOffset: { width: 0, height: 7 }, shadowRadius: 14, elevation: 2 },
  resolvedIcon: { width: 46, height: 46, borderRadius: 18, alignItems: 'center', justifyContent: 'center', marginRight: 14 },
  resolvedCopy: { flex: 1 },
  resolvedTitle: { color: '#07111F', fontSize: 17, fontWeight: '900' },
  resolvedTime: { color: '#93A1BA', fontSize: 14, fontWeight: '700', marginTop: 4 },
  filterRow: { flexDirection: 'row', alignItems: 'center', gap: 10, marginTop: 16, marginBottom: 16 },
  filterChip: { color: '#66738A', fontSize: 14, fontWeight: '900', paddingHorizontal: 16, paddingVertical: 11, borderRadius: 20, backgroundColor: '#EEF3F9' },
  filterChipActive: { color: '#FFFFFF', backgroundColor: '#1299F5' },
  alertCard: { borderWidth: 1.5, borderRadius: 18, backgroundColor: '#FFF1F3', padding: 18, marginBottom: 16 },
  alertTop: { flexDirection: 'row' },
  alertIcon: { width: 56, height: 56, borderRadius: 22, alignItems: 'center', justifyContent: 'center', marginRight: 14 },
  alertCopy: { flex: 1 },
  alertTitleRow: { flexDirection: 'row', alignItems: 'flex-start' },
  alertTitle: { flex: 1, color: '#07111F', fontSize: 18, lineHeight: 24, fontWeight: '900' },
  priorityPill: { borderWidth: 1, borderRadius: 14, paddingHorizontal: 8, paddingVertical: 3, fontSize: 12, fontWeight: '900', marginLeft: 8 },
  closePill: { width: 34, height: 34, borderRadius: 17, alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(255,255,255,0.72)', marginLeft: -6, marginTop: -7 },
  alertBody: { color: '#647189', fontSize: 15, lineHeight: 22, marginTop: 6 },
  alertMetaRow: { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 11, flexWrap: 'wrap' },
  alertMeta: { color: '#8EA0BB', fontSize: 14, fontWeight: '700' },
  actionRow: { flexDirection: 'row', gap: 10, marginTop: 18 },
  actionBtn: { flex: 1, height: 46, borderRadius: 23, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8 },
  actionText: { color: '#FFFFFF', fontSize: 15, fontWeight: '900' },
  emergencyBtn: { backgroundColor: '#EF3442' },
  warningBtn: { backgroundColor: '#F59E0B' },
  callBtn: { backgroundColor: '#08ADEC', borderWidth: 0 },
  secondaryBtn: { backgroundColor: '#FFFFFF', borderWidth: 1, borderColor: '#F6C77B' },
  infoBtn: { backgroundColor: '#FFFFFF', borderWidth: 1, borderColor: '#B8DAFF' },
  infoActionText: { color: '#0B84FF' },
});

function LegacyAlertsScreen() {
  const [alerts, setAlerts] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [checkPoints, setCheckPoints] = useState<CheckPoint[]>(FALLBACK_POINTS);
  const [gpsReady, setGpsReady] = useState(false);

  // Fetch user's real GPS once on mount and build dynamic monitored points.
  const initLocation = useCallback(async () => {
    try {
      const { status } = await Location.requestForegroundPermissionsAsync();
      if (status !== 'granted') {
        setCheckPoints(FALLBACK_POINTS);
        setGpsReady(false);
        return;
      }
      const loc = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
      const pts = buildCheckPointsAround(loc.coords.latitude, loc.coords.longitude);
      setCheckPoints(pts);
      setGpsReady(true);
    } catch (e) {
      console.warn('[ALERTS] GPS init failed, using fallback:', (e as any)?.message || e);
      setCheckPoints(FALLBACK_POINTS);
      setGpsReady(false);
    }
  }, []);

  const fetchAlerts = useCallback(async (points: CheckPoint[]) => {
    setScanning(true);
    const newAlerts: any[] = [];
    for (const point of points) {
      try {
        const res = await predictiveAlertService.evaluateWithAlternative(
          point.lat, point.lng, point.speed, point.heading,
        );
        if (res.data?.alerts?.length > 0) {
          newAlerts.push(...res.data.alerts.map((a: any) => ({ ...a, checkpoint: point.name })));
        }
      } catch {}
    }
    setAlerts(newAlerts);
    setLoading(false);
    setScanning(false);
  }, []);

  // On mount: GPS first, then scan
  useEffect(() => {
    (async () => {
      await initLocation();
    })();
  }, [initLocation]);

  // Once checkPoints are ready, run a scan
  useEffect(() => {
    if (checkPoints.length > 0) {
      fetchAlerts(checkPoints);
    }
  }, [checkPoints, fetchAlerts]);

  const onRefresh = async () => {
    setRefreshing(true);
    await initLocation();
    await fetchAlerts(checkPoints);
    setRefreshing(false);
  };

  const handleScanPress = () => fetchAlerts(checkPoints);

  return (
    <SafeAreaView style={styles.safe} testID="alerts-screen">
      <ScrollView
        style={styles.scroll}
        contentContainerStyle={styles.content}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.primary} />}
      >
        <Text style={styles.title}>Predictive Alerts</Text>
        <Text style={styles.subtitle}>
          AI-powered risk predictions for nearby areas
        </Text>

        {/* Scan Button */}
        <TouchableOpacity
          style={[styles.scanBtn, scanning && styles.btnDisabled]}
          onPress={handleScanPress}
          disabled={scanning}
          testID="scan-alerts-btn"
        >
          {scanning ? (
            <ActivityIndicator color={colors.white} />
          ) : (
            <>
              <Ionicons name="radio" size={20} color={colors.white} />
              <Text style={styles.scanBtnText}>Scan Area</Text>
            </>
          )}
        </TouchableOpacity>

        {/* Summary */}
        <View style={styles.summaryRow}>
          <View style={styles.summaryItem}>
            <Text style={styles.summaryNum}>{alerts.length}</Text>
            <Text style={styles.summaryLabel}>Active Alerts</Text>
          </View>
          <View style={styles.summaryItem}>
            <Text style={[styles.summaryNum, { color: colors.critical }]}>
              {alerts.filter(a => a.severity === 'high' || a.severity === 'critical').length}
            </Text>
            <Text style={styles.summaryLabel}>High Risk</Text>
          </View>
          <View style={styles.summaryItem}>
            <Text style={styles.summaryNum}>{checkPoints.length}</Text>
            <Text style={styles.summaryLabel}>Areas Checked</Text>
          </View>
        </View>

        {!gpsReady && (
          <View style={styles.gpsBanner}>
            <Ionicons name="location-outline" size={16} color={colors.warning} />
            <Text style={styles.gpsBannerText}>
              Location unavailable — enable location to scan your area.
            </Text>
          </View>
        )}

        {/* Alert Cards */}
        {loading ? (
          <View style={styles.loadingBox}>
            <ActivityIndicator size="large" color={colors.primary} />
            <Text style={styles.loadingText}>Scanning nearby areas...</Text>
          </View>
        ) : alerts.length === 0 ? (
          <View style={styles.emptyCard}>
            <Ionicons name="shield-checkmark" size={48} color={colors.safe} />
            <Text style={styles.emptyTitle}>All Clear</Text>
            <Text style={styles.emptyDesc}>No safety alerts in your area right now</Text>
          </View>
        ) : (
          alerts.map((alert, i) => <AlertCard key={i} alert={alert} index={i} />)
        )}

        {/* Check Points */}
        <Text style={styles.sectionTitle}>Monitored Areas</Text>
        {checkPoints.map((p, i) => (
          <View key={i} style={styles.checkpointCard}>
            <Ionicons name="location" size={18} color={colors.primary} />
            <View style={styles.checkpointInfo}>
              <Text style={styles.checkpointName}>{p.name}</Text>
              <Text style={styles.checkpointCoords}>{p.lat.toFixed(4)}, {p.lng.toFixed(4)}</Text>
            </View>
            <Ionicons name="checkmark-circle" size={18} color={colors.safe} />
          </View>
        ))}
      </ScrollView>
    </SafeAreaView>
  );
}

function AlertCard({ alert, index }: { alert: any; index: number }) {
  const severityColor = riskColor(alert.severity || 'moderate');
  return (
    <View style={[styles.alertCard, { borderLeftColor: severityColor, borderLeftWidth: 3 }]} testID={`alert-card-${index}`}>
      <View style={styles.alertHeader}>
        <View style={[styles.severityBadge, { backgroundColor: severityColor + '20' }]}>
          <Text style={[styles.severityText, { color: severityColor }]}>
            {(alert.severity || 'unknown').toUpperCase()}
          </Text>
        </View>
        {alert.checkpoint && (
          <Text style={styles.alertCheckpoint}>{alert.checkpoint}</Text>
        )}
      </View>
      <Text style={styles.alertType}>{alert.type || alert.alert_type || 'Risk Alert'}</Text>
      {alert.message && <Text style={styles.alertMsg}>{alert.message}</Text>}
      {alert.distance_meters != null && (
        <Text style={styles.alertDist}>{Math.round(alert.distance_meters)}m ahead</Text>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.bg },
  scroll: { flex: 1 },
  content: { padding: spacing.xl, paddingBottom: spacing['5xl'] },
  title: { fontSize: fontSize['2xl'], fontWeight: '800', color: colors.textPrimary },
  subtitle: { fontSize: fontSize.sm, color: colors.textSecondary, marginBottom: spacing.xl },
  scanBtn: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: spacing.sm, backgroundColor: colors.primary, borderRadius: radius.lg, height: 48, marginBottom: spacing.xl },
  scanBtnText: { color: colors.white, fontSize: fontSize.md, fontWeight: '700' },
  btnDisabled: { opacity: 0.6 },
  summaryRow: { flexDirection: 'row', gap: spacing.md, marginBottom: spacing.xl },
  summaryItem: { flex: 1, backgroundColor: colors.bgCard, borderRadius: radius.lg, padding: spacing.lg, alignItems: 'center', borderWidth: 1, borderColor: colors.border },
  summaryNum: { fontSize: fontSize['2xl'], fontWeight: '800', color: colors.textPrimary },
  summaryLabel: { fontSize: fontSize.xs, color: colors.textMuted, marginTop: 2 },
  loadingBox: { backgroundColor: colors.bgCard, borderRadius: radius.xl, padding: spacing['4xl'], alignItems: 'center', gap: spacing.md },
  loadingText: { fontSize: fontSize.md, color: colors.textSecondary },
  emptyCard: { backgroundColor: colors.bgCard, borderRadius: radius.xl, padding: spacing['4xl'], alignItems: 'center', gap: spacing.md, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.xl },
  emptyTitle: { fontSize: fontSize.xl, fontWeight: '700', color: colors.safe },
  emptyDesc: { fontSize: fontSize.sm, color: colors.textSecondary },
  alertCard: { backgroundColor: colors.bgCard, borderRadius: radius.lg, padding: spacing.lg, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.md },
  alertHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: spacing.sm },
  severityBadge: { paddingHorizontal: spacing.md, paddingVertical: 2, borderRadius: radius.full },
  severityText: { fontSize: fontSize.xs, fontWeight: '800', letterSpacing: 1 },
  alertCheckpoint: { fontSize: fontSize.xs, color: colors.textMuted },
  alertType: { fontSize: fontSize.md, fontWeight: '700', color: colors.textPrimary, marginBottom: 4, textTransform: 'capitalize' },
  alertMsg: { fontSize: fontSize.sm, color: colors.textSecondary },
  alertDist: { fontSize: fontSize.xs, color: colors.textMuted, marginTop: spacing.xs },
  sectionTitle: { fontSize: fontSize.lg, fontWeight: '700', color: colors.textPrimary, marginTop: spacing.xl, marginBottom: spacing.md },
  checkpointCard: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, backgroundColor: colors.bgCard, borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.sm },
  checkpointInfo: { flex: 1 },
  checkpointName: { fontSize: fontSize.sm, fontWeight: '600', color: colors.textPrimary },
  checkpointCoords: { fontSize: fontSize.xs, color: colors.textMuted },
  gpsBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    backgroundColor: colors.warning + '15',
    borderColor: colors.warning + '40',
    borderWidth: 1,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    marginBottom: spacing.lg,
  },
  gpsBannerText: {
    flex: 1,
    fontSize: fontSize.xs,
    color: colors.warning,
  },
});
