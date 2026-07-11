// NISCH-007 Part B — Guardian Incident Feed screen.
//
// Slots into the (tabs) router as the "Incidents" tab.
//
// Behavior:
//   * Map / Feed segmented toggle at top
//   * Zone filter chips below the toggle
//   * Both views share the same `incidents` state — flipping the toggle
//     never re-fetches
//   * SSE patches existing rows in place; new incidents prepend with a
//     200 ms teal flash; resolved incidents fade out of the active view
//   * SSE stale → 30 s polling fallback (canceled the moment SSE recovers)
//
// Data shape: the /nearby endpoint returns `marker_lat`/`marker_lng`
// already rounded to 3 decimal places (~111m) by the backend — that's
// our privacy contract: directionally accurate but never exposes the
// child's precise GPS. When the child has no fix, those fields come
// back `null` and `IncidentMapView` falls back to a per-id bearing
// ray-cast so the marker still has a stable position on the map.
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { KeyboardAvoidingView, Platform, View, StyleSheet, TouchableOpacity, Text, ActivityIndicator, ScrollView, Alert, TextInput } from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';

import { colors } from '@/theme';
import api from '@/services/api';
import { useGuardianSSE, isGuardianSSEAlive } from '@/hooks/useGuardianSSE';
import { useGPSLocation } from '@/hooks/useGPSLocation';

import { ZoneFilterBar, ZoneKey } from '@/components/incidents/ZoneFilterBar';
import { IncidentFeedList }       from '@/components/incidents/IncidentFeedList';
import { IncidentMapView, SavedZone } from '@/components/incidents/IncidentMapView';
import { IncidentMarkerSheet }    from '@/components/incidents/IncidentMarkerSheet';
import type { FeedIncident }      from '@/components/incidents/IncidentFeedRow';

const POLL_FALLBACK_MS = 30_000;
const FLASH_DURATION_MS = 200;

type ViewMode = 'map' | 'feed';

export default function ProtectionCenterScreen() {
  return <ReferenceProtectionCenter />;
}

function ReferenceProtectionCenter() {
  const router = useRouter();
  const [showZoneManager, setShowZoneManager] = useState(false);
  const [controls, setControls] = useState<Record<string, boolean>>({
    ai: true,
    location: false,
    microphone: false,
    sos: true,
    route: true,
    wearable: false,
  });

  if (showZoneManager) {
    return <SafeZoneManagerScreen onBack={() => setShowZoneManager(false)} />;
  }

  return (
    <SafeAreaView style={protectionRef.safe} edges={['top']}>
      <ScrollView style={protectionRef.scroll} contentContainerStyle={protectionRef.content} showsVerticalScrollIndicator={false}>
        <View style={protectionRef.hero}>
          <Text style={protectionRef.heroEyebrow}>SAFETY INFRASTRUCTURE</Text>
          <Text style={protectionRef.heroTitle}>Protection Center</Text>
          <View style={protectionRef.statRow}>
            <StatBox value="100%" label="AI Active" color="#4ADE80" />
            <StatBox value="4/4" label="Routes OK" color="#22D3EE" />
            <StatBox value="2/3" label="Devices" color="#FBBF24" />
          </View>
        </View>

        <View style={protectionRef.body}>
          <View style={protectionRef.warningCard}>
            <Ionicons name="warning-outline" size={26} color="#EF4444" />
            <View style={{ flex: 1 }}>
              <Text style={protectionRef.warningTitle}>Protection Compromised</Text>
              <Text style={protectionRef.warningText}>Location Monitoring is disabled. Protected member may not be fully protected.</Text>
            </View>
          </View>

          <SectionHead title="MONITORING CONTROLS" />
          <View style={protectionRef.controlCard}>
            <ControlRow icon="pulse-outline" title="AI Safety Monitoring" desc="Detects distress patterns in real-time" color="#0EA5E9" enabled={controls.ai} onPress={() => setControls((v) => ({ ...v, ai: !v.ai }))} />
            <ControlRow icon="location-outline" title="Location Monitoring" desc="Currently disabled" color="#94A3B8" enabled={controls.location} onPress={() => setControls((v) => ({ ...v, location: !v.location }))} />
            <ControlRow icon="mic-outline" title="Microphone Monitoring" desc="Disabled by Member" color="#94A3B8" warning enabled={controls.microphone} onPress={() => setControls((v) => ({ ...v, microphone: !v.microphone }))} />
            <ControlRow icon="flash-outline" title="SOS System" desc="One-tap emergency activation" color="#EF4444" enabled={controls.sos} onPress={() => setControls((v) => ({ ...v, sos: !v.sos }))} />
            <ControlRow icon="navigate-circle-outline" title="Route Monitoring" desc="Tracks journey & deviations" color="#06B6D4" enabled={controls.route} onPress={() => setControls((v) => ({ ...v, route: !v.route }))} />
            <ControlRow icon="watch-outline" title="Wearable Integration" desc="Permission Not Granted" color="#94A3B8" danger enabled={controls.wearable} onPress={() => setControls((v) => ({ ...v, wearable: !v.wearable }))} last />
          </View>

          <SectionHead title="SAFE ZONES" action="+ Add Zone" onAction={() => setShowZoneManager(true)} />
          <SafeZone name="Home" distance="200m" address="A-24 Sector 62, Noida" />
          <SafeZone name="School" distance="100m" address="DPS School, Sector 30" />
          <SafeZone name="Office" distance="150m" address="Cyber City, Gurugram" />

          <TouchableOpacity activeOpacity={0.84} style={protectionRef.manageZones} onPress={() => setShowZoneManager(true)}>
            <Text style={protectionRef.manageZonesText}>Manage Safe Zones & Restricted Zones {'->'}</Text>
          </TouchableOpacity>

          <SectionHead title="WEARABLE DEVICES" action="+ Pair Device" onAction={() => Alert.alert('Pair Device', 'Pair smart watch, safety band, or emergency keychain.')} />
          <WearableRow name="Priya's Watch" type="Smart Watch" status="Connected" meta="72% battery" color="#0EA5E9" />
          <WearableRow name="Nana's Keychain" type="Emergency Keychain" status="Connected" meta="88% battery" color="#22C55E" />
          <WearableRow name="Riya's Band" type="Fitness Band" status="Disconnected" meta="" color="#94A3B8" disconnected />

          <TouchableOpacity activeOpacity={0.86} style={protectionRef.dpdpCard} onPress={() => router.push('/privacy')}>
            <Ionicons name="shield-outline" size={22} color="#3B82F6" />
            <View style={{ flex: 1 }}>
              <Text style={protectionRef.dpdpTitle}>DPDP Compliant</Text>
              <Text style={protectionRef.dpdpText}>All monitoring requires member consent. Manage permissions in Settings.</Text>
            </View>
          </TouchableOpacity>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

function SafeZoneManagerScreen({ onBack }: { onBack: () => void }) {
  const [tab, setTab] = useState<'safe' | 'restricted'>('safe');
  const [showSafeForm, setShowSafeForm] = useState(false);
  const [showRestrictedForm, setShowRestrictedForm] = useState(false);
  const [radius, setRadius] = useState<'100m' | '500m' | '1km'>('500m');

  const safeZones = [
    { icon: 'home-outline', name: 'Home', address: 'B-42, Sector 15, Noida, UP', radius: '500m', chips: ['Aarav: Inside', 'Nana: Inside', 'Priya: Outside'] },
    { icon: 'school-outline', name: 'School', address: 'DPS Sector 19, Noida, UP', radius: '100m', chips: ['Aarav: Inside', 'Priya: Inside'] },
    { icon: 'medkit-outline', name: 'Hospital', address: 'Fortis Hospital, Sector 62, Noida', radius: '500m', chips: ['Nana: Outside'] },
    { icon: 'barbell-outline', name: 'Gym', address: 'Anytime Fitness, Sector 18, Noida', radius: '100m', chips: ['Priya: Outside'] },
    { icon: 'library-outline', name: 'Tuition', address: 'Aakash Institute, Sector 10, Noida', radius: '100m', chips: ['Aarav: Outside'] },
    { icon: 'business-outline', name: 'Office', address: 'Logix Techno Park, Sector 132, Noida', radius: '1km', chips: ['Priya: Outside'] },
  ];

  const resetSafeForm = () => setShowSafeForm(false);
  const resetRestrictedForm = () => setShowRestrictedForm(false);

  return (
    <SafeAreaView style={zoneRef.safe} edges={['top']}>
      <KeyboardAvoidingView style={zoneRef.flex} behavior={Platform.OS === 'ios' ? 'padding' : 'height'}>
        <View style={zoneRef.header}>
          <TouchableOpacity activeOpacity={0.82} onPress={onBack} style={zoneRef.backBtn}>
            <Ionicons name="chevron-back" size={26} color="#0F172A" />
          </TouchableOpacity>
          <View style={zoneRef.headerCopy}>
            <Text style={zoneRef.title}>Safe Zones</Text>
            <Text style={zoneRef.subtitle}>6 active zones</Text>
          </View>
          <Ionicons name="shield-outline" size={24} color="#0B84FF" />
        </View>

        <ScrollView style={zoneRef.scroll} contentContainerStyle={zoneRef.content} keyboardShouldPersistTaps="handled" keyboardDismissMode="on-drag" showsVerticalScrollIndicator={false}>
          <View style={zoneRef.segment}>
            <TouchableOpacity activeOpacity={0.82} onPress={() => setTab('safe')} style={[zoneRef.segmentBtn, tab === 'safe' && zoneRef.segmentSafeActive]}>
              <Text style={[zoneRef.segmentText, tab === 'safe' && zoneRef.segmentActiveText]}>Safe Zones</Text>
            </TouchableOpacity>
            <TouchableOpacity activeOpacity={0.82} onPress={() => setTab('restricted')} style={[zoneRef.segmentBtn, tab === 'restricted' && zoneRef.segmentRestrictedActive]}>
              <Text style={[zoneRef.segmentText, tab === 'restricted' && zoneRef.segmentActiveText]}>Restricted Zones</Text>
            </TouchableOpacity>
          </View>

          <ZoneMapPreview />

          {tab === 'safe' ? (
            <>
              {safeZones.map((zone) => (
                <ZoneManageCard key={zone.name} {...zone} />
              ))}
              {showSafeForm ? (
                <View style={zoneRef.safeForm}>
                  <Text style={zoneRef.formTitle}>New Safe Zone</Text>
                  <TextInput style={zoneRef.formInput} placeholder="Zone name (e.g. Park)" placeholderTextColor="#94A3B8" />
                  <TextInput style={zoneRef.formInput} placeholder="Address or landmark" placeholderTextColor="#94A3B8" />
                  <Text style={zoneRef.radiusLabel}>Radius</Text>
                  <View style={zoneRef.radiusRow}>
                    {(['100m', '500m', '1km'] as const).map((item) => (
                      <TouchableOpacity key={item} activeOpacity={0.82} onPress={() => setRadius(item)} style={[zoneRef.radiusBtn, radius === item && zoneRef.radiusActive]}>
                        <Text style={[zoneRef.radiusText, radius === item && zoneRef.radiusActiveText]}>{item}</Text>
                      </TouchableOpacity>
                    ))}
                  </View>
                  <View style={zoneRef.formActions}>
                    <TouchableOpacity activeOpacity={0.82} onPress={resetSafeForm} style={zoneRef.cancelBtn}>
                      <Text style={zoneRef.cancelText}>Cancel</Text>
                    </TouchableOpacity>
                    <TouchableOpacity activeOpacity={0.86} onPress={resetSafeForm} style={zoneRef.addSafeBtn}>
                      <Text style={zoneRef.addBtnText}>Add Zone</Text>
                    </TouchableOpacity>
                  </View>
                </View>
              ) : (
                <TouchableOpacity activeOpacity={0.86} onPress={() => setShowSafeForm(true)} style={zoneRef.addSafeZoneBtn}>
                  <Ionicons name="add" size={26} color="#FFFFFF" />
                  <Text style={zoneRef.addZoneBtnText}>Add Safe Zone</Text>
                </TouchableOpacity>
              )}
            </>
          ) : (
            <>
              {showRestrictedForm ? (
                <View style={zoneRef.restrictedForm}>
                  <Text style={zoneRef.formTitle}>New Restricted Zone</Text>
                  <TextInput style={zoneRef.formInput} placeholder="Zone name (e.g. Park)" placeholderTextColor="#94A3B8" />
                  <TextInput style={zoneRef.formInput} placeholder="Address or landmark" placeholderTextColor="#94A3B8" />
                  <View style={zoneRef.formActions}>
                    <TouchableOpacity activeOpacity={0.82} onPress={resetRestrictedForm} style={zoneRef.cancelBtn}>
                      <Text style={zoneRef.cancelText}>Cancel</Text>
                    </TouchableOpacity>
                    <TouchableOpacity activeOpacity={0.86} onPress={resetRestrictedForm} style={zoneRef.addRestrictedBtn}>
                      <Text style={zoneRef.addBtnText}>Add Zone</Text>
                    </TouchableOpacity>
                  </View>
                </View>
              ) : (
                <View style={zoneRef.emptyRestricted}>
                  <View style={zoneRef.emptyIcon}>
                    <Ionicons name="close-outline" size={42} color="#EF4444" />
                  </View>
                  <Text style={zoneRef.emptyTitle}>No Restricted Zones</Text>
                  <Text style={zoneRef.emptySub}>Add areas your family member should avoid.{'\n'}You'll get an instant alert if they enter.</Text>
                  <TouchableOpacity activeOpacity={0.86} onPress={() => setShowRestrictedForm(true)} style={zoneRef.addRestrictedZoneBtn}>
                    <Ionicons name="add" size={26} color="#FFFFFF" />
                    <Text style={zoneRef.addZoneBtnText}>Add Restricted Zone</Text>
                  </TouchableOpacity>
                </View>
              )}
            </>
          )}
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

function ZoneMapPreview() {
  return (
    <View style={zoneRef.map}>
      {Array.from({ length: 7 }).map((_, index) => <View key={`zv-${index}`} style={[zoneRef.mapV, { left: `${index * 16.6}%` }]} />)}
      {Array.from({ length: 5 }).map((_, index) => <View key={`zh-${index}`} style={[zoneRef.mapH, { top: `${index * 24}%` }]} />)}
      <View style={[zoneRef.zonePin, zoneRef.pinBlue]}><Ionicons name="location" size={28} color="#0B84FF" /></View>
      <View style={[zoneRef.zonePin, zoneRef.pinGreen]}><Ionicons name="location" size={28} color="#22C55E" /></View>
      <View style={[zoneRef.zonePin, zoneRef.pinOrange]}><Ionicons name="location" size={28} color="#F59E0B" /></View>
      <View style={zoneRef.parkBox}><Text style={zoneRef.mapTiny}>Park</Text></View>
      <View style={zoneRef.schoolMapBox}><Text style={zoneRef.mapTinyBlue}>School</Text></View>
      <Text style={zoneRef.mapWatermark}>NISCHINT Map</Text>
    </View>
  );
}

function ZoneManageCard({ icon, name, address, radius, chips }: any) {
  return (
    <View style={zoneRef.zoneCard}>
      <View style={zoneRef.zoneIcon}><Ionicons name={icon as keyof typeof Ionicons.glyphMap} size={26} color="#0B84FF" /></View>
      <View style={zoneRef.zoneCopy}>
        <View style={zoneRef.zoneTop}>
          <View style={{ flex: 1, minWidth: 0 }}>
            <Text style={zoneRef.zoneName}>{name}</Text>
            <Text style={zoneRef.zoneAddress} numberOfLines={1}>{address}</Text>
          </View>
          <Text style={zoneRef.zoneRadius}>{radius}</Text>
          <Ionicons name="chevron-down" size={18} color="#8AA0BC" />
        </View>
        <View style={zoneRef.chipsRow}>
          {chips.map((chip: string) => {
            const inside = chip.includes('Inside');
            return (
              <Text key={chip} style={[zoneRef.memberChip, !inside && zoneRef.memberChipOutside]}>
                {inside ? '⊙ ' : '⊗ '}{chip}
              </Text>
            );
          })}
        </View>
      </View>
    </View>
  );
}

function StatBox({ value, label, color }: { value: string; label: string; color: string }) {
  return (
    <View style={protectionRef.statBox}>
      <Text style={[protectionRef.statValue, { color }]}>{value}</Text>
      <Text style={protectionRef.statLabel}>{label}</Text>
    </View>
  );
}

function SectionHead({ title, action, onAction }: { title: string; action?: string; onAction?: () => void }) {
  return (
    <View style={protectionRef.sectionHead}>
      <Text style={protectionRef.sectionTitle}>{title}</Text>
      {action ? (
        <TouchableOpacity activeOpacity={0.78} onPress={onAction}>
          <Text style={protectionRef.sectionAction}>{action}</Text>
        </TouchableOpacity>
      ) : null}
    </View>
  );
}

function ControlRow({ icon, title, desc, color, enabled, onPress, warning, danger, last }: any) {
  return (
    <View style={[protectionRef.controlRow, !last && protectionRef.controlBorder]}>
      <View style={[protectionRef.controlIcon, { backgroundColor: `${color}14` }]}>
        <Ionicons name={icon} size={25} color={color} />
      </View>
      <View style={protectionRef.controlCopy}>
        <Text style={protectionRef.controlTitle}>{title}</Text>
        <Text style={[protectionRef.controlDesc, warning && protectionRef.warningDesc, danger && protectionRef.dangerDesc]} numberOfLines={1}>{desc}</Text>
      </View>
      <TouchableOpacity activeOpacity={0.82} onPress={onPress} style={[protectionRef.switchTrack, enabled && protectionRef.switchOn]}>
        <View style={[protectionRef.switchKnob, enabled && protectionRef.switchKnobOn]} />
      </TouchableOpacity>
    </View>
  );
}

function SafeZone({ name, distance, address }: { name: string; distance: string; address: string }) {
  return (
    <View style={protectionRef.zoneCard}>
      <View style={protectionRef.zoneIcon}><Ionicons name="location-outline" size={25} color="#0B84FF" /></View>
      <View style={{ flex: 1 }}>
        <View style={protectionRef.zoneTitleRow}>
          <Text style={protectionRef.zoneName}>{name}</Text>
          <Text style={protectionRef.zoneDistance}>{distance}</Text>
        </View>
        <Text style={protectionRef.zoneAddress}>{address}</Text>
      </View>
      <View style={protectionRef.greenDot} />
    </View>
  );
}

function WearableRow({ name, type, status, meta, color, disconnected }: any) {
  return (
    <View style={[protectionRef.wearableCard, disconnected && protectionRef.wearableDisabled]}>
      <View style={[protectionRef.zoneIcon, { backgroundColor: `${color}14` }]}><Ionicons name="watch-outline" size={24} color={color} /></View>
      <View style={{ flex: 1 }}>
        <Text style={[protectionRef.zoneName, disconnected && protectionRef.disabledText]}>{name}</Text>
        <Text style={protectionRef.zoneAddress}>{type}</Text>
      </View>
      <View style={{ alignItems: 'flex-end' }}>
        <Text style={[protectionRef.deviceStatus, disconnected && protectionRef.deviceDisconnected]}>{status}</Text>
        {meta ? <Text style={protectionRef.deviceMeta}>{meta}</Text> : null}
      </View>
    </View>
  );
}

const zoneRef = StyleSheet.create({
  safe: { flex: 1, backgroundColor: '#F5F7FB' },
  flex: { flex: 1 },
  header: { minHeight: 132, backgroundColor: '#FFFFFF', borderBottomWidth: 1, borderBottomColor: '#E5ECF4', flexDirection: 'row', alignItems: 'center', gap: 14, paddingHorizontal: 18, paddingTop: 28 },
  backBtn: { width: 46, height: 46, borderRadius: 23, backgroundColor: '#F1F5F9', alignItems: 'center', justifyContent: 'center' },
  headerCopy: { flex: 1 },
  title: { color: '#07111F', fontSize: 24, fontWeight: '900' },
  subtitle: { color: '#52647C', fontSize: 15, fontWeight: '700', marginTop: 3 },
  scroll: { flex: 1 },
  content: { paddingHorizontal: 18, paddingTop: 20, paddingBottom: 122 },
  segment: { flexDirection: 'row', gap: 10, backgroundColor: '#F5F7FB', marginBottom: 28 },
  segmentBtn: { flex: 1, minHeight: 46, borderRadius: 18, backgroundColor: '#EEF2F7', alignItems: 'center', justifyContent: 'center' },
  segmentSafeActive: { backgroundColor: '#0B91FF' },
  segmentRestrictedActive: { backgroundColor: '#EF4444' },
  segmentText: { color: '#607084', fontSize: 16, fontWeight: '900' },
  segmentActiveText: { color: '#FFFFFF' },
  map: { height: 180, borderRadius: 16, overflow: 'hidden', backgroundColor: '#EAF4FF', marginBottom: 16 },
  mapV: { position: 'absolute', top: 0, bottom: 0, width: 1.2, backgroundColor: '#B8D8FF' },
  mapH: { position: 'absolute', left: 0, right: 0, height: 1.2, backgroundColor: '#B8D8FF' },
  zonePin: { position: 'absolute', width: 48, height: 48, borderRadius: 24, borderWidth: 2, borderStyle: 'dashed', alignItems: 'center', justifyContent: 'center' },
  pinBlue: { left: '48%', top: '24%', borderColor: '#0B84FF' },
  pinGreen: { left: '18%', top: '55%', borderColor: '#22C55E' },
  pinOrange: { right: '18%', top: '38%', borderColor: '#F59E0B' },
  parkBox: { position: 'absolute', left: '28%', top: '55%', width: 76, height: 50, borderRadius: 7, borderWidth: 1, borderColor: '#6EE7B7', backgroundColor: '#CFFAE7', alignItems: 'center', justifyContent: 'center' },
  schoolMapBox: { position: 'absolute', right: '29%', top: '20%', width: 70, height: 46, borderRadius: 6, borderWidth: 1, borderColor: '#93C5FD', backgroundColor: '#D9EAFF', alignItems: 'center', justifyContent: 'center' },
  mapTiny: { color: '#0F8F61', fontSize: 10, fontWeight: '800' },
  mapTinyBlue: { color: '#2563EB', fontSize: 10, fontWeight: '800' },
  mapWatermark: { position: 'absolute', right: 14, bottom: 14, color: '#64748B', fontSize: 13, fontWeight: '800' },
  zoneCard: { minHeight: 118, borderRadius: 18, borderWidth: 1, borderColor: '#DCE5EF', backgroundColor: '#FFFFFF', flexDirection: 'row', alignItems: 'flex-start', gap: 14, padding: 18, marginBottom: 16 },
  zoneIcon: { width: 52, height: 52, borderRadius: 18, backgroundColor: '#EAF4FF', alignItems: 'center', justifyContent: 'center' },
  zoneCopy: { flex: 1, minWidth: 0 },
  zoneTop: { flexDirection: 'row', alignItems: 'flex-start', gap: 8 },
  zoneName: { color: '#07111F', fontSize: 19, fontWeight: '900' },
  zoneAddress: { color: '#8A9AB3', fontSize: 15, fontWeight: '700', marginTop: 4 },
  zoneRadius: { color: '#2563EB', fontSize: 15, fontWeight: '900', paddingHorizontal: 10, paddingVertical: 5, borderRadius: 13, backgroundColor: '#EEF6FF', overflow: 'hidden' },
  chipsRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 16 },
  memberChip: { color: '#067A3D', fontSize: 14, fontWeight: '900', paddingHorizontal: 8, paddingVertical: 4, borderRadius: 11, backgroundColor: '#E4FBEA', overflow: 'hidden' },
  memberChipOutside: { color: '#64748B', backgroundColor: '#F1F5F9' },
  addSafeZoneBtn: { minHeight: 66, borderRadius: 15, backgroundColor: '#0B84FF', flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 10, marginTop: 6, shadowColor: '#0B84FF', shadowOpacity: 0.22, shadowOffset: { width: 0, height: 10 }, shadowRadius: 20, elevation: 3 },
  addRestrictedZoneBtn: { minHeight: 66, borderRadius: 15, backgroundColor: '#EF333A', flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 10, marginTop: 32, shadowColor: '#EF333A', shadowOpacity: 0.2, shadowOffset: { width: 0, height: 10 }, shadowRadius: 20, elevation: 3 },
  addZoneBtnText: { color: '#FFFFFF', fontSize: 18, fontWeight: '900' },
  emptyRestricted: { alignItems: 'center', paddingTop: 56 },
  emptyIcon: { width: 96, height: 96, borderRadius: 48, backgroundColor: '#FEE2E6', alignItems: 'center', justifyContent: 'center', marginBottom: 22 },
  emptyTitle: { color: '#07111F', fontSize: 21, fontWeight: '900' },
  emptySub: { color: '#607084', fontSize: 17, lineHeight: 25, fontWeight: '600', textAlign: 'center', marginTop: 14 },
  safeForm: { borderWidth: 1, borderColor: '#9BD3FF', borderRadius: 17, backgroundColor: '#EAF6FF', padding: 20, marginTop: 6 },
  restrictedForm: { borderWidth: 1, borderColor: '#FDA4AF', borderRadius: 17, backgroundColor: '#FFF1F3', padding: 20, marginTop: 30 },
  formTitle: { color: '#07111F', fontSize: 19, fontWeight: '900', marginBottom: 16 },
  formInput: { minHeight: 48, borderRadius: 18, borderWidth: 1, borderColor: '#DCE5EF', backgroundColor: '#FFFFFF', paddingHorizontal: 16, color: '#07111F', fontSize: 16, fontWeight: '700', marginBottom: 12 },
  radiusLabel: { color: '#607084', fontSize: 15, fontWeight: '800', marginTop: 4, marginBottom: 10 },
  radiusRow: { flexDirection: 'row', gap: 10, marginBottom: 20 },
  radiusBtn: { flex: 1, minHeight: 44, borderRadius: 14, borderWidth: 1, borderColor: '#DCE5EF', backgroundColor: '#FFFFFF', alignItems: 'center', justifyContent: 'center' },
  radiusActive: { backgroundColor: '#0B84FF', borderColor: '#0B84FF' },
  radiusText: { color: '#64748B', fontSize: 15, fontWeight: '900' },
  radiusActiveText: { color: '#FFFFFF' },
  formActions: { flexDirection: 'row', gap: 10 },
  cancelBtn: { flex: 1, minHeight: 52, borderRadius: 17, borderWidth: 1, borderColor: '#DCE5EF', backgroundColor: '#FFFFFF', alignItems: 'center', justifyContent: 'center' },
  cancelText: { color: '#64748B', fontSize: 17, fontWeight: '900' },
  addSafeBtn: { flex: 1, minHeight: 52, borderRadius: 17, backgroundColor: '#0B84FF', alignItems: 'center', justifyContent: 'center' },
  addRestrictedBtn: { flex: 1, minHeight: 52, borderRadius: 17, backgroundColor: '#EF4444', alignItems: 'center', justifyContent: 'center' },
  addBtnText: { color: '#FFFFFF', fontSize: 17, fontWeight: '900' },
});

const protectionRef = StyleSheet.create({
  safe: { flex: 1, backgroundColor: '#F5F7FB' },
  scroll: { flex: 1 },
  content: { paddingBottom: 92 },
  hero: { backgroundColor: '#162E4D', paddingHorizontal: 30, paddingTop: 72, paddingBottom: 26 },
  heroEyebrow: { color: '#A7B9D0', fontSize: 13, fontWeight: '900', letterSpacing: 2 },
  heroTitle: { color: '#FFFFFF', fontSize: 26, fontWeight: '900', marginTop: 8 },
  statRow: { flexDirection: 'row', gap: 10, marginTop: 24 },
  statBox: { flex: 1, height: 72, borderRadius: 16, alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(255,255,255,0.10)' },
  statValue: { fontSize: 22, fontWeight: '900' },
  statLabel: { color: '#B6C6D9', fontSize: 12, fontWeight: '800', marginTop: 6 },
  body: { paddingHorizontal: 24, paddingTop: 20 },
  warningCard: { minHeight: 106, borderRadius: 18, borderWidth: 1, borderColor: '#FDA4AF', backgroundColor: '#FFF1F3', flexDirection: 'row', alignItems: 'flex-start', gap: 14, padding: 20 },
  warningTitle: { color: '#F04455', fontSize: 18, fontWeight: '900' },
  warningText: { color: '#607084', fontSize: 15, lineHeight: 23, fontWeight: '600', marginTop: 5 },
  sectionHead: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginTop: 22, marginBottom: 12 },
  sectionTitle: { color: '#60799D', fontSize: 15, fontWeight: '900', letterSpacing: 2 },
  sectionAction: { color: '#0B84FF', fontSize: 15, fontWeight: '900' },
  controlCard: { borderRadius: 18, backgroundColor: '#FFFFFF', overflow: 'hidden', shadowColor: '#0F172A', shadowOpacity: 0.07, shadowOffset: { width: 0, height: 10 }, shadowRadius: 24, elevation: 4 },
  controlRow: { minHeight: 86, flexDirection: 'row', alignItems: 'center', gap: 14, paddingHorizontal: 20 },
  controlBorder: { borderBottomWidth: 1, borderBottomColor: '#EEF2F7' },
  controlIcon: { width: 52, height: 52, borderRadius: 19, alignItems: 'center', justifyContent: 'center' },
  controlCopy: { flex: 1, minWidth: 0 },
  controlTitle: { color: '#07111F', fontSize: 17, fontWeight: '900' },
  controlDesc: { color: '#52647C', fontSize: 14, fontWeight: '600', marginTop: 5 },
  warningDesc: { color: '#F59E0B' },
  dangerDesc: { color: '#EF3442' },
  switchTrack: { width: 62, height: 34, borderRadius: 17, backgroundColor: '#E2E8F0', padding: 3 },
  switchOn: { backgroundColor: '#0EA5E9' },
  switchKnob: { width: 28, height: 28, borderRadius: 14, backgroundColor: '#FFFFFF' },
  switchKnobOn: { marginLeft: 28 },
  zoneCard: { minHeight: 84, borderRadius: 16, backgroundColor: '#FFFFFF', flexDirection: 'row', alignItems: 'center', gap: 14, paddingHorizontal: 18, marginBottom: 12, shadowColor: '#0F172A', shadowOpacity: 0.06, shadowOffset: { width: 0, height: 8 }, shadowRadius: 18, elevation: 2 },
  zoneIcon: { width: 52, height: 52, borderRadius: 19, alignItems: 'center', justifyContent: 'center', backgroundColor: '#EAF4FF' },
  zoneTitleRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  zoneName: { color: '#07111F', fontSize: 17, fontWeight: '900' },
  zoneDistance: { overflow: 'hidden', color: '#16A34A', fontSize: 12, fontWeight: '900', paddingHorizontal: 8, paddingVertical: 4, borderRadius: 10, backgroundColor: '#DCFCE7' },
  zoneAddress: { color: '#52647C', fontSize: 14, fontWeight: '600', marginTop: 5 },
  greenDot: { width: 10, height: 10, borderRadius: 5, backgroundColor: '#22C55E' },
  manageZones: { height: 48, borderRadius: 16, borderWidth: 1.2, borderColor: '#0B84FF', alignItems: 'center', justifyContent: 'center', marginTop: 2 },
  manageZonesText: { color: '#0B84FF', fontSize: 16, fontWeight: '900' },
  wearableCard: { minHeight: 84, borderRadius: 16, backgroundColor: '#FFFFFF', flexDirection: 'row', alignItems: 'center', gap: 14, paddingHorizontal: 18, marginBottom: 12, shadowColor: '#0F172A', shadowOpacity: 0.06, shadowOffset: { width: 0, height: 8 }, shadowRadius: 18, elevation: 2 },
  wearableDisabled: { opacity: 0.72 },
  disabledText: { color: '#64748B' },
  deviceStatus: { color: '#22C55E', fontSize: 12, fontWeight: '900' },
  deviceDisconnected: { color: '#EF6771' },
  deviceMeta: { color: '#94A3B8', fontSize: 12, fontWeight: '700', marginTop: 7 },
  dpdpCard: { minHeight: 98, borderRadius: 17, borderWidth: 1, borderColor: '#B8DAFF', backgroundColor: '#EEF6FF', flexDirection: 'row', alignItems: 'flex-start', gap: 14, padding: 18, marginTop: 8 },
  dpdpTitle: { color: '#3B82F6', fontSize: 15, fontWeight: '900' },
  dpdpText: { color: '#52647C', fontSize: 14, lineHeight: 21, fontWeight: '600', marginTop: 4 },
});

function LegacyIncidentFeed() {
  const router = useRouter();
  const gps = useGPSLocation({ watchPosition: true });

  const [mode, setMode]               = useState<ViewMode>('feed');
  const [zone, setZone]               = useState<ZoneKey>('all');
  const [incidents, setIncidents]     = useState<FeedIncident[]>([]);
  const [refreshing, setRefreshing]   = useState(false);
  const [loading, setLoading]         = useState(true);
  const [activeId, setActiveId]       = useState<string | null>(null);
  const [savedZones, setSavedZones]   = useState<SavedZone[]>([]);
  // NISCH-008 — incident_id → live stream_id mapping. Populated by
  // the guardian SSE channel (`stream_available` events). Cleared
  // when the stream ends. Used by the marker sheet to show the
  // "🔴 LIVE — tap to listen" affordance.
  const [liveStreams, setLiveStreams] = useState<Record<string, string>>({});

  const pollTimerRef   = useRef<ReturnType<typeof setInterval> | null>(null);
  const flashTimersRef = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());

  // ── 1. Fetch loop ────────────────────────────────────────────────
  const fetchIncidents = useCallback(async (silent = false) => {
    if (!gps.latitude || !gps.longitude) return;
    if (!silent) setLoading(true);
    try {
      const params: Record<string, string | number> = {
        lat:    gps.latitude,
        lng:    gps.longitude,
        radius: 500,
        status: 'active',
        limit:  20,
      };
      if (zone !== 'all') params.zone = zone;
      const res = await api.get('/incidents/nearby', { params });
      const list: FeedIncident[] = (res.data?.incidents || []).map((i: any) => ({
        id:                       i.id,
        state:                    i.state,
        state_label:              i.state_label,
        severity:                 i.severity,
        distance_metres:          i.distance_metres,
        zone_match:               i.zone_match,
        elapsed_since_created:    i.elapsed_since_created,
        sla_degraded_at_dispatch: !!i.sla_degraded_at_dispatch,
        // Privacy-rounded marker coords (3dp ~111m). May be null when
        // the child has no location fix — IncidentMapView handles the
        // bearing fallback in that case.
        marker_lat: i.marker_lat == null ? null : Number(i.marker_lat),
        marker_lng: i.marker_lng == null ? null : Number(i.marker_lng),
      }));
      setIncidents(list);
    } catch (e: any) {
      if (__DEV__) console.warn('[INCIDENT_FEED] fetch failed:', e?.message);
    } finally {
      if (!silent) setLoading(false);
      setRefreshing(false);
    }
  }, [gps.latitude, gps.longitude, zone]);

  // ── 2. Initial fetch + zone-change refetch ───────────────────────
  useEffect(() => {
    fetchIncidents();
  }, [fetchIncidents]);

  // ── 3. Saved zones (best-effort, silent on failure) ─────────────
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await api.get('/zones');
        const list: SavedZone[] = (res.data?.zones || res.data || [])
          .filter((z: any) => z.active !== false)
          .map((z: any) => ({
            id:         String(z.id),
            lat:        Number(z.lat),
            lng:        Number(z.lng),
            radius_m:   Number(z.radius_m || 100),
            zone_type:  String(z.zone_type || 'custom'),
          }))
          .filter((z: SavedZone) => Number.isFinite(z.lat) && Number.isFinite(z.lng));
        if (!cancelled) setSavedZones(list);
      } catch {
        // Silent — zones are decorative
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // ── 4. SSE patch loop ────────────────────────────────────────────
  useGuardianSSE(useCallback((eventType: string, payload: any) => {
    // NISCH-008 — guardian-side stream lifecycle. We track which
    // incident has a live stream so the marker sheet can render
    // a "🔴 LIVE — tap to listen" affordance.
    if (eventType === 'stream_available' && payload?.stream_id && payload?.incident_id) {
      setLiveStreams((prev) => ({
        ...prev,
        [payload.incident_id]: payload.stream_id,
      }));
      return;
    }
    if (eventType === 'stream_state' && payload?.stream_id) {
      const s = payload.state;
      if (s === 'ended' || s === 'declined') {
        setLiveStreams((prev) => {
          const next: Record<string, string> = {};
          for (const [iid, sid] of Object.entries(prev)) {
            if (sid !== payload.stream_id) next[iid] = sid;
          }
          return next;
        });
      }
      return;
    }

    // We listen to BOTH `incident_state_change` (Day 3 forensic stream)
    // and `incident_created` / `incident_updated` (existing pipeline
    // events) so the feed reflects truth from any path.
    const interesting =
      eventType === 'incident_state_change' ||
      eventType === 'incident_created' ||
      eventType === 'incident_updated';
    if (!interesting) return;

    const inc = payload?.incident || payload;
    const id = inc?.id || inc?.incident_id;
    if (!id) return;

    const newState: string | undefined = inc?.state || inc?.to_state;
    setIncidents((curr) => {
      const idx = curr.findIndex((c) => c.id === id);

      // Resolved → drop from `active` view (the only view we render).
      if (newState === 'resolved' || newState === 'archived') {
        return idx >= 0 ? curr.filter((c) => c.id !== id) : curr;
      }

      if (idx >= 0) {
        // In-place patch — preserve _flash, distance, zone_match.
        const next = [...curr];
        next[idx] = {
          ...next[idx],
          state:        newState || next[idx].state,
          state_label:  inc?.state_label || next[idx].state_label,
          severity:     inc?.severity    || next[idx].severity,
        };
        return next;
      }

      // New row → prepend with flash; trigger a refetch shortly to
      // hydrate distance + zone fields the SSE payload lacks.
      const placeholder: FeedIncident = {
        id,
        state:                    newState || 'detected',
        state_label:              inc?.state_label || 'New incident',
        severity:                 inc?.severity || 'medium',
        distance_metres:          inc?.distance_metres ?? 0,
        zone_match:               inc?.zone_match ?? null,
        elapsed_since_created:    inc?.elapsed_since_created || 'just now',
        sla_degraded_at_dispatch: !!inc?.sla_degraded_at_dispatch,
        // SSE payload doesn't carry rounded markers. Bearing fallback
        // takes over in the map view until the refetch hydrates.
        marker_lat:               null,
        marker_lng:               null,
        _flash: true,
      };
      // Schedule flash clear.
      const t = setTimeout(() => {
        flashTimersRef.current.delete(id);
        setIncidents((cs) => cs.map((c) =>
          c.id === id ? { ...c, _flash: false } : c
        ));
      }, FLASH_DURATION_MS);
      flashTimersRef.current.set(id, t);
      // Hydrate full fields from the API.
      fetchIncidents(true);
      return [placeholder, ...curr];
    });
  }, [fetchIncidents]));

  // ── 5. Polling fallback when SSE is stale/down ───────────────────
  useEffect(() => {
    const tick = () => {
      if (!isGuardianSSEAlive()) {
        fetchIncidents(true);
      }
    };
    pollTimerRef.current = setInterval(tick, POLL_FALLBACK_MS);
    return () => {
      if (pollTimerRef.current) clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    };
  }, [fetchIncidents]);

  // ── 6. Cleanup flash timers on unmount ───────────────────────────
  useEffect(() => () => {
    flashTimersRef.current.forEach((t) => clearTimeout(t));
    flashTimersRef.current.clear();
  }, []);

  // ── 7. Map data — pass incidents straight through. The map view
  //       picks privacy-rounded `marker_lat`/`marker_lng` from the
  //       API and falls back to a stable per-id bearing when null.
  const centre = useMemo(
    () => ({ lat: gps.latitude || 19.0760, lng: gps.longitude || 72.8777 }),
    [gps.latitude, gps.longitude]
  );

  // ── 8. Handlers ──────────────────────────────────────────────────
  const handleRowPress = useCallback((id: string) => {
    router.push({ pathname: '/incident-timeline', params: { id } } as any);
  }, [router]);

  const onPullToRefresh = useCallback(() => {
    setRefreshing(true);
    fetchIncidents(true);
  }, [fetchIncidents]);

  const activeIncident = activeId
    ? incidents.find((i) => i.id === activeId) || null
    : null;

  // ── 9. Render ────────────────────────────────────────────────────
  return (
    <SafeAreaView style={styles.root} edges={['top']}>
      <View style={styles.header}>
        <Text style={styles.title}>Nearby Incidents</Text>
        <View style={styles.toggle}>
          <ToggleBtn
            active={mode === 'feed'}
            label="Feed"
            onPress={() => setMode('feed')}
            testID="toggle-feed"
          />
          <ToggleBtn
            active={mode === 'map'}
            label="Map"
            onPress={() => setMode('map')}
            testID="toggle-map"
          />
        </View>
      </View>

      <ZoneFilterBar active={zone} onChange={setZone} />

      {loading && incidents.length === 0 ? (
        <View style={styles.loading}>
          <ActivityIndicator color={colors.primary} />
        </View>
      ) : mode === 'feed' ? (
        <IncidentFeedList
          incidents={incidents}
          refreshing={refreshing}
          onRefresh={onPullToRefresh}
          onRowPress={handleRowPress}
        />
      ) : (
        <IncidentMapView
          centre={centre}
          incidents={incidents}
          savedZones={savedZones}
          onMarkerPress={setActiveId}
          onRecentre={() => {}}
        />
      )}

      <IncidentMarkerSheet
        incident={activeIncident}
        liveStreamId={activeId ? liveStreams[activeId] || null : null}
        onClose={() => setActiveId(null)}
        onViewTimeline={(id) => {
          setActiveId(null);
          handleRowPress(id);
        }}
      />
    </SafeAreaView>
  );
}

function ToggleBtn({
  active, label, onPress, testID,
}: { active: boolean; label: string; onPress: () => void; testID: string }) {
  return (
    <TouchableOpacity
      testID={testID}
      onPress={onPress}
      activeOpacity={0.85}
      style={[styles.toggleBtn, active && styles.toggleBtnActive]}
    >
      <Text style={[styles.toggleText, active && styles.toggleTextActive]}>
        {label}
      </Text>
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: colors.bg,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingTop: 12,
    paddingBottom: 8,
  },
  title: {
    fontSize: 22,
    fontWeight: '700',
    color: colors.textPrimary,
  },
  toggle: {
    flexDirection: 'row',
    backgroundColor: colors.bgCard,
    borderRadius: 10,
    padding: 3,
  },
  toggleBtn: {
    paddingHorizontal: 14,
    paddingVertical: 6,
    borderRadius: 8,
  },
  toggleBtnActive: {
    backgroundColor: colors.primary,
  },
  toggleText: {
    fontSize: 13,
    fontWeight: '600',
    color: colors.textSecondary,
  },
  toggleTextActive: {
    color: colors.white,
  },
  loading: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
});
