// Guardian / Share Tab — Guardian Family Dashboard for guardians, Share Safety for users
import { useState, useEffect, useCallback } from 'react';
import React from 'react';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity,
  RefreshControl, Alert, Share, ActivityIndicator, TextInput,
  Linking,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { LinearGradient } from 'expo-linear-gradient';
import { Ionicons } from '@expo/vector-icons';
import { useFocusEffect } from '@react-navigation/native';
import { useRouter } from 'expo-router';
import { useAuthStore } from '@/stores/authStore';
import { guardianDashboardService, guardianService, safetyScoreService, locationShareService, guardianLinkService } from '@/services/endpoints';
import { colors, spacing, fontSize, radius, shadows, riskColor, scoreColor, scoreLabel } from '@/theme';
import { ImpactBadge } from '@/components/guardian/ImpactBadge';

export default function GuardianScreen() {
  const { profileMode } = useAuthStore();
  if (profileMode === 'women') {
    return <WomanSafeWalkScreen />;
  }
  if (['kids', 'women', 'senior', 'family'].includes(profileMode)) {
    return <ChildRoutesScreen />;
  }
  return <LegacyGuardianScreen />;
}

function WomanSafeWalkScreen() {
  const router = useRouter();
  const [journeyStarted, setJourneyStarted] = useState(false);
  const [destination, setDestination] = useState('');

  const handleJourneyPress = () => {
    if (journeyStarted) {
      router.push('/(tabs)/journey');
      return;
    }
    setJourneyStarted(true);
  };

  return (
    <SafeAreaView style={safeWalkRef.safe} edges={['top']}>
      <View style={safeWalkRef.header}>
        <TouchableOpacity activeOpacity={0.82} style={safeWalkRef.backBtn}>
          <Ionicons name="chevron-back" size={26} color="#0F172A" />
        </TouchableOpacity>
        <View style={safeWalkRef.headerCenter}>
          <Text style={safeWalkRef.headerName}>swaesrgh</Text>
          <View style={safeWalkRef.roleRow}>
            <View style={safeWalkRef.roleDot} />
            <Text style={safeWalkRef.roleText}>Woman - Protected</Text>
          </View>
        </View>
        <Text style={safeWalkRef.womanPill}>Woman</Text>
      </View>

      <ScrollView style={safeWalkRef.scroll} contentContainerStyle={safeWalkRef.content} showsVerticalScrollIndicator={false}>
        <Text style={safeWalkRef.title}>Safe Walk</Text>
        <View style={safeWalkRef.statusLine}>
          <View style={[safeWalkRef.statusDot, journeyStarted && safeWalkRef.statusDotActive]} />
          <Text style={safeWalkRef.statusText}>
            {journeyStarted ? 'Journey in progress - guardian watching' : 'Ready to start'}
          </Text>
        </View>

        <View style={safeWalkRef.destinationCard}>
          <Text style={safeWalkRef.cardLabel}>DESTINATION</Text>
          <View style={safeWalkRef.destinationRow}>
            <Ionicons name="location-outline" size={26} color="#0A84FF" />
            <TextInput
              value={destination}
              onChangeText={setDestination}
              placeholder="Enter your destination..."
              placeholderTextColor="#CBD5E1"
              style={safeWalkRef.destinationInput}
            />
          </View>
        </View>

        <View style={safeWalkRef.guardianCard}>
          <View style={safeWalkRef.guardianIcon}>
            <Ionicons name="shield-outline" size={28} color="#22C55E" />
          </View>
          <View style={safeWalkRef.guardianCopy}>
            <Text style={safeWalkRef.guardianTitle}>Guardian Watching</Text>
            <Text style={safeWalkRef.guardianSub}>Mom - Dad - Emergency contact</Text>
          </View>
          <View style={[safeWalkRef.guardianIndicator, journeyStarted && safeWalkRef.guardianIndicatorActive]} />
        </View>

        <View style={safeWalkRef.routeCard}>
          <View style={safeWalkRef.routeTitleRow}>
            <Ionicons name="navigate-outline" size={25} color="#0A84FF" />
            <Text style={safeWalkRef.routeTitle}>Safe Route</Text>
          </View>
          <View style={safeWalkRef.mapPreview}>
            <Text style={safeWalkRef.mapText}>{destination.trim() ? `Route to "${destination.trim()}"` : 'Enter destination to see route'}</Text>
          </View>
        </View>

        <TouchableOpacity
          activeOpacity={0.86}
          onPress={handleJourneyPress}
          style={[safeWalkRef.primaryButton, journeyStarted && safeWalkRef.endButton]}
        >
          <Text style={safeWalkRef.primaryButtonText}>{journeyStarted ? 'End Journey' : 'Start Safe Walk'}</Text>
        </TouchableOpacity>
      </ScrollView>
    </SafeAreaView>
  );
}

function ChildRoutesScreen() {
  return (
    <SafeAreaView style={routeRef.safe} edges={['top']}>
      <ScrollView style={routeRef.scroll} contentContainerStyle={routeRef.content} showsVerticalScrollIndicator={false}>
        <View style={routeRef.hero}>
          <Text style={routeRef.eyebrow}>TODAY'S JOURNEY</Text>
          <Text style={routeRef.title}>My Routes</Text>
          <Text style={routeRef.date}>Thursday, Jun 12</Text>
        </View>

        <RouteJourneyCard
          title="Home -> School"
          status="Arrived"
          statusTone="#16A34A"
          progress={100}
          left="Left 8:15 AM"
          right="Arrived 8:42 AM"
          distance="4.2 km"
          duration="27 min"
          safety="Safe ✅"
        />
        <RouteJourneyCard
          title="School -> Home"
          status="⏳ Pending"
          statusTone="#B45309"
          progress={0}
          left="◷ Expected 3:05 PM"
          right="School ends 2:30 PM"
          distance="4.2 km"
          duration="~27 min"
          safety="Waiting"
        />

        <Text style={routeRef.sectionLabel}>SAFE ZONES</Text>
        <View style={routeRef.zoneRow}>
          <View style={routeRef.zoneCard}>
            <View style={[routeRef.zoneIcon, { backgroundColor: '#DCFCE7' }]}>
              <Ionicons name="home-outline" size={28} color="#22C55E" />
            </View>
            <Text style={routeRef.zoneTitle}>Home</Text>
            <Text style={routeRef.zoneStatus}>⊙ Inside</Text>
          </View>
          <View style={routeRef.zoneCard}>
            <View style={[routeRef.zoneIcon, { backgroundColor: '#EAF5FF' }]}>
              <Ionicons name="location-outline" size={28} color="#0A84FF" />
            </View>
            <Text style={routeRef.zoneTitle}>School</Text>
            <Text style={routeRef.zoneStatus}>⊙ Inside</Text>
          </View>
        </View>

        <View style={routeRef.guardianWatch}>
          <View style={routeRef.guardianIcon}>
            <Ionicons name="shield-outline" size={28} color="#FFFFFF" />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={routeRef.guardianTitle}>Guardian watching your route</Text>
            <Text style={routeRef.guardianSub}>Papa & Mummy are notified of every stop</Text>
          </View>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

function RouteJourneyCard({ title, status, statusTone, progress, left, right, distance, duration, safety }: any) {
  return (
    <View style={routeRef.routeCard}>
      <View style={routeRef.routeHead}>
        <Text style={routeRef.routeTitle}>{title}</Text>
        <Text style={[routeRef.routeStatus, { color: statusTone }]}>{status}</Text>
      </View>
      <View style={routeRef.progressTrack}>
        <View style={[routeRef.progressFill, { width: `${progress}%`, backgroundColor: progress ? '#2CCB73' : '#EEF2F7' }]} />
      </View>
      <View style={routeRef.timeRow}>
        <Text style={routeRef.timeText}>{left}</Text>
        <Text style={routeRef.timeText}>{right}</Text>
      </View>
      <View style={routeRef.metricRow}>
        <View style={routeRef.metricCell}>
          <Text style={routeRef.metricLabel}>Distance</Text>
          <Text style={routeRef.metricValue}>{distance}</Text>
        </View>
        <View style={routeRef.metricCell}>
          <Text style={routeRef.metricLabel}>Duration</Text>
          <Text style={routeRef.metricValue}>{duration}</Text>
        </View>
        <View style={routeRef.metricCell}>
          <Text style={routeRef.metricLabel}>Status</Text>
          <Text style={routeRef.metricValue}>{safety}</Text>
        </View>
      </View>
    </View>
  );
}

function ReferenceSettingsScreen() {
  const sections = [
    {
      title: 'ACCOUNT',
      items: [
        ['person-outline', '#0EA5E9', 'Profile', 'Rajesh Sharma - +91 98765 43210'],
        ['people-outline', '#22C55E', 'Family Circle', '1 Member - 1 Co-Parent - Manage'],
        ['diamond-outline', '#F59E0B', 'Subscription', 'Premium - Rs299/mo - Add Members'],
        ['card-outline', '#35D07F', 'Billing & Invoices', 'Next renewal: 15 Jan 2026'],
      ],
    },
    {
      title: 'PRIVACY & COMPLIANCE',
      items: [
        ['shield-checkmark-outline', '#4F8CF7', 'DPDP Consent Dashboard', 'Manage data permissions'],
        ['eye-outline', '#0EA5E9', 'Privacy Policy', 'How NISCHINT uses your data'],
        ['document-text-outline', '#8B5CF6', 'Terms & Conditions', 'Legal terms of service'],
        ['download-outline', '#22C55E', 'Download My Data', 'Export all your NISCHINT data'],
        ['trash-outline', '#EF3442', 'Delete Account', 'Requires OTP + 72hr cooling'],
      ],
    },
    {
      title: 'SECURITY',
      items: [
        ['lock-closed-outline', '#22C55E', 'Two-Factor Auth', 'Enabled - SMS verification'],
        ['phone-portrait-outline', '#8B5CF6', 'Active Sessions', '2 devices logged in'],
        ['key-outline', '#0EA5E9', 'Change Password', 'Last changed 3 months ago'],
      ],
    },
    {
      title: 'EMERGENCY CONTACTS',
      items: [
        ['call-outline', '#F59E0B', 'Manage Contacts', '4 contacts - SOS order'],
      ],
    },
    {
      title: 'NOTIFICATIONS',
      items: [
        ['alert-circle-outline', '#EF3442', 'SOS Alerts', 'Always on - Critical'],
        ['sparkles-outline', '#0EA5E9', 'AI Safety Alerts', 'Smart threat notifications'],
        ['map-outline', '#F59E0B', 'Route Alerts', 'Deviation & arrival'],
        ['battery-charging-outline', '#8B5CF6', 'Battery Alerts', 'On - Below 20%'],
        ['cloud-offline-outline', '#64748B', 'Device Alerts', 'On - Offline detection'],
      ],
    },
    {
      title: 'CONNECTED DEVICES',
      items: [
        ['watch-outline', '#0EA5E9', 'Wearables & Watch', '2 devices paired'],
        ['hardware-chip-outline', '#22C55E', 'Safety Keychain', '1 active - Battery 88%'],
      ],
    },
    {
      title: 'HISTORY & DATA',
      items: [
        ['location-outline', '#4F8CF7', 'Location History', 'View all tracked locations'],
        ['navigate-outline', '#22C55E', 'Route History', 'Journey playback'],
        ['time-outline', '#F59E0B', 'Alert History', 'All alerts & notifications'],
      ],
    },
  ];

  return (
    <SafeAreaView style={settingsRef.safe} edges={['top']}>
      <ScrollView style={settingsRef.scroll} contentContainerStyle={settingsRef.content} showsVerticalScrollIndicator={false}>
        <View style={settingsRef.hero}>
          <View style={settingsRef.heroRow}>
            <View style={settingsRef.brandRow}>
              <View style={settingsRef.logoCircle}>
                <Ionicons name="shield-checkmark" size={27} color="#12D0CF" />
              </View>
              <View>
                <Text style={settingsRef.personName}>Rajesh Sharma</Text>
                <Text style={settingsRef.personMeta}>Primary Guardian - Premium</Text>
              </View>
            </View>
            <Ionicons name="settings-outline" size={23} color="#16C7C7" />
          </View>
        </View>

        <LinearGradient colors={['#11B6F4', '#26E36E']} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={settingsRef.planCard}>
          <View>
            <Text style={settingsRef.planLabel}>ACTIVE PLAN</Text>
            <Text style={settingsRef.planName}>Premium Family Circle</Text>
            <Text style={settingsRef.planMeta}>1 Parent - 1 Co-Parent - 1 Member</Text>
          </View>
          <View style={settingsRef.priceWrap}>
            <Text style={settingsRef.price}>Rs299</Text>
            <Text style={settingsRef.perMonth}>/month</Text>
          </View>
          <View style={settingsRef.planButtons}>
            <TouchableOpacity style={settingsRef.manageBtn} activeOpacity={0.85}>
              <Text style={settingsRef.manageText}>Manage Plan</Text>
            </TouchableOpacity>
            <TouchableOpacity style={settingsRef.addBtn} activeOpacity={0.85}>
              <Text style={settingsRef.addText}>+ Add Member</Text>
            </TouchableOpacity>
          </View>
        </LinearGradient>

        {sections.map((section) => (
          <View key={section.title} style={settingsRef.section}>
            <Text style={settingsRef.sectionTitle}>{section.title}</Text>
            <View style={settingsRef.card}>
              {section.items.map(([icon, color, title, subtitle], index) => (
                <TouchableOpacity key={title} activeOpacity={0.78} style={[settingsRef.row, index > 0 && settingsRef.rowBorder]}>
                  <View style={[settingsRef.rowIcon, { backgroundColor: `${color}14` }]}>
                    <Ionicons name={icon as keyof typeof Ionicons.glyphMap} size={18} color={color} />
                  </View>
                  <View style={settingsRef.rowCopy}>
                    <Text style={settingsRef.rowTitle}>{title}</Text>
                    <Text style={settingsRef.rowSub}>{subtitle}</Text>
                  </View>
                  <Ionicons name="chevron-forward" size={18} color="#CBD5E1" />
                </TouchableOpacity>
              ))}
            </View>
          </View>
        ))}
      </ScrollView>
    </SafeAreaView>
  );
}

const safeWalkRef = StyleSheet.create({
  safe: { flex: 1, backgroundColor: '#F3F7FB' },
  header: { minHeight: 90, backgroundColor: '#FFFFFF', borderBottomWidth: 1, borderBottomColor: '#E2E8F0', flexDirection: 'row', alignItems: 'center', paddingHorizontal: 20 },
  backBtn: { width: 42, height: 42, borderRadius: 21, backgroundColor: '#F1F5F9', alignItems: 'center', justifyContent: 'center' },
  headerCenter: { flex: 1, alignItems: 'center' },
  headerName: { color: '#06122A', fontSize: 18, fontWeight: '900' },
  roleRow: { flexDirection: 'row', alignItems: 'center', gap: 7, marginTop: 6 },
  roleDot: { width: 8, height: 8, borderRadius: 4, backgroundColor: '#22C55E' },
  roleText: { color: '#7C3AED', fontSize: 13, fontWeight: '800' },
  womanPill: { overflow: 'hidden', borderRadius: 15, backgroundColor: '#F3E8FF', color: '#7C3AED', paddingHorizontal: 12, paddingVertical: 8, fontSize: 13, fontWeight: '900' },
  scroll: { flex: 1 },
  content: { paddingHorizontal: 24, paddingTop: 32, paddingBottom: 108 },
  title: { color: '#06122A', fontSize: 31, fontWeight: '900' },
  statusLine: { flexDirection: 'row', alignItems: 'center', gap: 10, marginTop: 10 },
  statusDot: { width: 10, height: 10, borderRadius: 5, backgroundColor: '#94A3B8' },
  statusDotActive: { backgroundColor: '#4ADE80' },
  statusText: { color: '#60708A', fontSize: 19, fontWeight: '700' },
  destinationCard: { minHeight: 106, borderRadius: 17, backgroundColor: '#FFFFFF', marginTop: 22, padding: 22, shadowColor: '#0F172A', shadowOpacity: 0.08, shadowOffset: { width: 0, height: 4 }, shadowRadius: 10, elevation: 2 },
  cardLabel: { color: '#94A3B8', fontSize: 15, fontWeight: '900', letterSpacing: 1.3 },
  destinationRow: { flexDirection: 'row', alignItems: 'center', gap: 14, marginTop: 16 },
  placeholder: { color: '#CBD5E1', fontSize: 18, fontWeight: '700' },
  destinationInput: { flex: 1, color: '#07111F', fontSize: 18, fontWeight: '800', paddingVertical: 0 },
  guardianCard: { minHeight: 90, borderRadius: 17, backgroundColor: '#FFFFFF', marginTop: 22, paddingHorizontal: 22, flexDirection: 'row', alignItems: 'center', gap: 16, shadowColor: '#0F172A', shadowOpacity: 0.08, shadowOffset: { width: 0, height: 4 }, shadowRadius: 10, elevation: 2 },
  guardianIcon: { width: 52, height: 52, borderRadius: 26, alignItems: 'center', justifyContent: 'center', backgroundColor: '#ECFDF3' },
  guardianCopy: { flex: 1 },
  guardianTitle: { color: '#06122A', fontSize: 18, fontWeight: '900' },
  guardianSub: { color: '#53657E', fontSize: 15, fontWeight: '700', marginTop: 4 },
  guardianIndicator: { width: 13, height: 13, borderRadius: 7, backgroundColor: '#D8E2EE' },
  guardianIndicatorActive: { backgroundColor: '#22C55E' },
  routeCard: { minHeight: 202, borderRadius: 17, backgroundColor: '#FFFFFF', marginTop: 22, padding: 22, shadowColor: '#0F172A', shadowOpacity: 0.08, shadowOffset: { width: 0, height: 4 }, shadowRadius: 10, elevation: 2 },
  routeTitleRow: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  routeTitle: { color: '#06122A', fontSize: 18, fontWeight: '900' },
  mapPreview: { minHeight: 120, borderRadius: 16, backgroundColor: '#EDF8F7', alignItems: 'center', justifyContent: 'center', marginTop: 18 },
  mapText: { color: '#8EA0BB', fontSize: 15, fontWeight: '700' },
  primaryButton: { minHeight: 70, borderRadius: 16, backgroundColor: '#8B35E8', alignItems: 'center', justifyContent: 'center', marginTop: 22 },
  endButton: { backgroundColor: '#E92A2F' },
  primaryButtonText: { color: '#FFFFFF', fontSize: 20, fontWeight: '900' },
});

const routeRef = StyleSheet.create({
  safe: { flex: 1, backgroundColor: '#F3F7FB' },
  scroll: { flex: 1 },
  content: { paddingBottom: 108 },
  hero: { backgroundColor: '#18345A', paddingHorizontal: 26, paddingTop: 70, paddingBottom: 25 },
  eyebrow: { color: '#A9B7CB', fontSize: 13, fontWeight: '900', letterSpacing: 1.6 },
  title: { color: '#FFFFFF', fontSize: 30, fontWeight: '900', marginTop: 12 },
  date: { color: '#C5D3E6', fontSize: 16, fontWeight: '700', marginTop: 10 },
  routeCard: { marginHorizontal: 26, marginTop: 22, borderRadius: 28, backgroundColor: '#FFFFFF', overflow: 'hidden', shadowColor: '#0F172A', shadowOpacity: 0.07, shadowOffset: { width: 0, height: 10 }, shadowRadius: 20, elevation: 3 },
  routeHead: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 20, paddingTop: 22 },
  routeTitle: { color: '#06122A', fontSize: 22, fontWeight: '900' },
  routeStatus: { overflow: 'hidden', borderRadius: 16, backgroundColor: '#DCFCE7', paddingHorizontal: 13, paddingVertical: 7, fontSize: 15, fontWeight: '900' },
  progressTrack: { height: 10, borderRadius: 5, marginHorizontal: 20, marginTop: 18, backgroundColor: '#EEF2F7', overflow: 'hidden' },
  progressFill: { height: '100%', borderRadius: 5 },
  timeRow: { flexDirection: 'row', justifyContent: 'space-between', paddingHorizontal: 20, paddingVertical: 14 },
  timeText: { color: '#667590', fontSize: 15, fontWeight: '700' },
  metricRow: { minHeight: 80, flexDirection: 'row', borderTopWidth: 1, borderTopColor: '#EEF2F7' },
  metricCell: { flex: 1, alignItems: 'center', justifyContent: 'center', borderRightWidth: 1, borderRightColor: '#EEF2F7' },
  metricLabel: { color: '#94A3B8', fontSize: 13, fontWeight: '700' },
  metricValue: { color: '#06122A', fontSize: 18, fontWeight: '900', marginTop: 6 },
  sectionLabel: { color: '#60708A', fontSize: 15, fontWeight: '900', letterSpacing: 1.5, marginTop: 22, marginBottom: 14, paddingHorizontal: 26 },
  zoneRow: { flexDirection: 'row', gap: 16, paddingHorizontal: 26 },
  zoneCard: { flex: 1, minHeight: 140, borderRadius: 16, backgroundColor: '#FFFFFF', padding: 20, justifyContent: 'center', shadowColor: '#0F172A', shadowOpacity: 0.06, shadowOffset: { width: 0, height: 8 }, shadowRadius: 18, elevation: 2 },
  zoneIcon: { width: 48, height: 48, borderRadius: 24, alignItems: 'center', justifyContent: 'center' },
  zoneTitle: { color: '#06122A', fontSize: 19, fontWeight: '900', marginTop: 16 },
  zoneStatus: { color: '#16A34A', fontSize: 15, fontWeight: '900', marginTop: 12 },
  guardianWatch: { minHeight: 84, marginHorizontal: 26, marginTop: 20, borderRadius: 18, backgroundColor: '#1D426F', paddingHorizontal: 18, flexDirection: 'row', alignItems: 'center', gap: 14, shadowColor: '#1D426F', shadowOpacity: 0.22, shadowOffset: { width: 0, height: 12 }, shadowRadius: 18, elevation: 4 },
  guardianIcon: { width: 52, height: 52, borderRadius: 17, alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(255,255,255,0.12)' },
  guardianTitle: { color: '#FFFFFF', fontSize: 17, fontWeight: '900' },
  guardianSub: { color: '#CAD8EA', fontSize: 14, fontWeight: '700', marginTop: 4 },
});

const settingsRef = StyleSheet.create({
  safe: { flex: 1, backgroundColor: '#F5F7FB' },
  scroll: { flex: 1 },
  content: { paddingBottom: 18 },
  hero: { backgroundColor: '#132843', paddingHorizontal: 20, paddingTop: 22, paddingBottom: 18 },
  heroRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  brandRow: { flexDirection: 'row', alignItems: 'center' },
  logoCircle: { width: 43, height: 43, borderRadius: 16, alignItems: 'center', justifyContent: 'center', marginRight: 12, backgroundColor: 'rgba(12,198,214,0.12)' },
  personName: { color: '#FFFFFF', fontSize: 18, fontWeight: '900' },
  personMeta: { color: '#9FB5D1', fontSize: 12, fontWeight: '700', marginTop: 3 },
  planCard: { marginHorizontal: 20, marginTop: 16, borderRadius: 16, padding: 18, overflow: 'hidden' },
  planLabel: { color: 'rgba(255,255,255,0.72)', fontSize: 11, fontWeight: '900', letterSpacing: 1.2 },
  planName: { color: '#FFFFFF', fontSize: 18, fontWeight: '900', marginTop: 8 },
  planMeta: { color: 'rgba(255,255,255,0.86)', fontSize: 12, fontWeight: '700', marginTop: 5 },
  priceWrap: { position: 'absolute', top: 16, right: 18, alignItems: 'flex-end' },
  price: { color: '#FFFFFF', fontSize: 21, fontWeight: '900' },
  perMonth: { color: 'rgba(255,255,255,0.75)', fontSize: 11, fontWeight: '700' },
  planButtons: { flexDirection: 'row', gap: 10, marginTop: 18 },
  manageBtn: { flex: 1, height: 36, borderRadius: 18, alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(255,255,255,0.20)' },
  manageText: { color: '#FFFFFF', fontSize: 13, fontWeight: '900' },
  addBtn: { flex: 1, height: 36, borderRadius: 18, alignItems: 'center', justifyContent: 'center', backgroundColor: '#FFFFFF' },
  addText: { color: '#0EA5E9', fontSize: 13, fontWeight: '900' },
  section: { paddingHorizontal: 20, marginTop: 18 },
  sectionTitle: { color: '#748198', fontSize: 12, fontWeight: '900', letterSpacing: 1.3, marginBottom: 9 },
  card: { borderRadius: 16, backgroundColor: '#FFFFFF', overflow: 'hidden', shadowColor: '#0F172A', shadowOpacity: 0.05, shadowOffset: { width: 0, height: 8 }, shadowRadius: 18, elevation: 2 },
  row: { minHeight: 64, flexDirection: 'row', alignItems: 'center', paddingHorizontal: 14 },
  rowBorder: { borderTopWidth: 1, borderTopColor: '#EEF2F7' },
  rowIcon: { width: 34, height: 34, borderRadius: 12, alignItems: 'center', justifyContent: 'center', marginRight: 12 },
  rowCopy: { flex: 1 },
  rowTitle: { color: '#172033', fontSize: 14, fontWeight: '900' },
  rowSub: { color: '#8B98AA', fontSize: 11, fontWeight: '700', marginTop: 3 },
});

function LegacyGuardianScreen() {
  const { user } = useAuthStore();
  const role = (user?.role || '').toLowerCase();
  const isGuardian = ['guardian', 'parent', 'parents', 'caregiver'].includes(role);

  return isGuardian ? <ReferenceFamilyCircle /> : <ShareSafety />;
}

function ReferenceFamilyCircle() {
  const router = useRouter();
  const [showAddMemberSheet, setShowAddMemberSheet] = useState(false);

  const call = (phone = 'tel:112') => Linking.openURL(phone).catch(() => {});

  return (
    <SafeAreaView style={familyRef.safe} edges={['top']}>
      <ScrollView style={familyRef.scroll} contentContainerStyle={familyRef.content} showsVerticalScrollIndicator={false}>
        <View style={familyRef.hero}>
          <View style={familyRef.heroRow}>
            <View style={familyRef.logoMark}>
              <Ionicons name="shield-checkmark" size={30} color="#14C7C8" />
            </View>
            <View>
              <Text style={familyRef.heroEyebrow}>PROTECTION HIERARCHY</Text>
              <Text style={familyRef.heroTitle}>Family Circle</Text>
            </View>
          </View>
        </View>

        <View style={familyRef.hierarchyCard}>
          <View style={familyRef.cardHead}>
            <Text style={familyRef.sectionLabel}>PROTECTION HIERARCHY</Text>
            <Ionicons name="diamond-outline" size={22} color="#F59E0B" />
          </View>
          <FamilyNode name="Rajesh Sharma" badge="You" access="Full Control" accessTone="#0EA5E9" action="Call" onCall={() => call()} />
          <View style={familyRef.downLine}><Ionicons name="chevron-down" size={20} color="#B8CADB" /></View>
          <FamilyNode name="Sunita Sharma" access="Monitoring Access" accessTone="#22C55E" action="Call" onCall={() => call()} />
          <View style={familyRef.downLine}><Ionicons name="chevron-down" size={20} color="#B8CADB" /></View>
          <FamilyNode name="Priya Sharma" access="Protected Member" accessTone="#A78BFA" action="Call" secondaryAction="Track" onCall={() => call()} onTrack={() => router.push('/(tabs)/journey')} tall />
        </View>

        <View style={familyRef.statusHead}>
          <View style={familyRef.statusLeft}>
            <Ionicons name="shield-outline" size={20} color="#8B5CF6" />
            <Text style={familyRef.statusTitle}>Protected Member Status</Text>
          </View>
          <View style={familyRef.statusPill}>
            <Text style={familyRef.statusPillText}>Safe</Text>
            <Ionicons name="chevron-down" size={16} color="#7A8CA5" />
          </View>
        </View>

        <View style={familyRef.mapCard}>
          <View style={familyRef.mapCanvas}>
            {Array.from({ length: 8 }).map((_, index) => <View key={`mv-${index}`} style={[familyRef.mapV, { left: `${index * 14.28}%` }]} />)}
            {Array.from({ length: 6 }).map((_, index) => <View key={`mh-${index}`} style={[familyRef.mapH, { top: `${index * 19}%` }]} />)}
            <Text style={familyRef.routeBubble}>Route: Home {'->'} School</Text>
            <Text style={familyRef.updatedBubble}>Last updated: Just now</Text>
            <View style={familyRef.routeLine} />
            <View style={familyRef.routeDot} />
            <View style={familyRef.schoolBox}><Text style={familyRef.schoolText}>SCHOOL</Text></View>
            <View style={[familyRef.tree, { left: '22%', top: '22%' }]} />
            <View style={[familyRef.treeSmall, { left: '29%', top: '31%' }]} />
            <View style={[familyRef.tree, { right: '25%', bottom: '24%' }]} />
            <View style={[familyRef.treeSmall, { right: '18%', bottom: '18%' }]} />
            <View style={familyRef.zoomControls}>
              <Text style={familyRef.zoomText}>+</Text>
              <View style={familyRef.zoomDivider} />
              <Text style={familyRef.zoomText}>-</Text>
            </View>
          </View>
          <View style={familyRef.routeSummary}>
            <View style={familyRef.routeSummaryHead}>
              <Text style={familyRef.schoolRoute}>School Route</Text>
              <Text style={familyRef.arrivedText}>100% Arrived</Text>
            </View>
            <View style={familyRef.routeProgress}><LinearGradient colors={['#0EA5E9', '#22C55E']} style={familyRef.routeProgressFill} /></View>
            <View style={familyRef.routeLegend}>
              <Text style={familyRef.legendText}>Home</Text>
              <Text style={familyRef.legendText}>Current</Text>
              <Text style={familyRef.legendText}>School</Text>
            </View>
          </View>
        </View>

        <TouchableOpacity style={familyRef.addMember} activeOpacity={0.84} onPress={() => setShowAddMemberSheet(true)}>
          <Ionicons name="add" size={25} color="#0B84FF" />
          <Text style={familyRef.addMemberText}>Add Protected Member</Text>
        </TouchableOpacity>
      </ScrollView>

      {showAddMemberSheet ? (
        <View style={familyRef.sheetLayer}>
          <TouchableOpacity activeOpacity={1} style={familyRef.sheetBackdrop} onPress={() => setShowAddMemberSheet(false)} />
          <View style={familyRef.addSheet}>
            <View style={familyRef.sheetHead}>
              <Text style={familyRef.sheetTitle}>Add Protected Member</Text>
              <TouchableOpacity activeOpacity={0.82} onPress={() => setShowAddMemberSheet(false)} style={familyRef.sheetClose}>
                <Ionicons name="close" size={22} color="#64748B" />
              </TouchableOpacity>
            </View>
            <View style={familyRef.sheetPlusCircle}>
              <Ionicons name="add" size={32} color="#0B84FF" />
            </View>
            <Text style={familyRef.sheetPlanText}>Your plan includes 1 Protected Member</Text>
            <Text style={familyRef.sheetSubText}>Add more protected members for</Text>
            <Text style={familyRef.sheetPrice}>₹99/member/month</Text>
            <TouchableOpacity activeOpacity={0.88} style={familyRef.upgradeButton}>
              <Text style={familyRef.upgradeText}>Upgrade Plan</Text>
            </TouchableOpacity>
            <TouchableOpacity activeOpacity={0.82} onPress={() => setShowAddMemberSheet(false)} style={familyRef.notNowButton}>
              <Text style={familyRef.notNowText}>Not Now</Text>
            </TouchableOpacity>
          </View>
        </View>
      ) : null}
    </SafeAreaView>
  );
}

function FamilyNode({ name, badge, access, accessTone, action, secondaryAction, onCall, onTrack, tall }: any) {
  return (
    <View style={[familyRef.nodeCard, tall && familyRef.nodeTall]}>
      <View style={familyRef.photoStub} />
      <View style={familyRef.nodeCopy}>
        <View style={familyRef.nameRow}>
          <Text style={familyRef.nodeName}>{name}</Text>
          {badge ? <Text style={familyRef.youBadge}>{badge}</Text> : null}
        </View>
        <Text style={[familyRef.accessBadge, { color: accessTone, backgroundColor: `${accessTone}16` }]}>{access}</Text>
        <View style={familyRef.nodeOnline} />
      </View>
      <View style={familyRef.actionWrap}>
        <TouchableOpacity style={familyRef.callBtn} activeOpacity={0.84} onPress={onCall}>
          <Ionicons name="call-outline" size={16} color="#FFFFFF" />
          <Text style={familyRef.callText}>{action}</Text>
        </TouchableOpacity>
        {secondaryAction ? (
          <TouchableOpacity style={familyRef.trackBtn} activeOpacity={0.84} onPress={onTrack}>
            <Ionicons name="location-outline" size={16} color="#FFFFFF" />
            <Text style={familyRef.callText}>{secondaryAction}</Text>
          </TouchableOpacity>
        ) : null}
      </View>
    </View>
  );
}

const familyRef = StyleSheet.create({
  safe: { flex: 1, backgroundColor: '#F5F7FB' },
  scroll: { flex: 1 },
  content: { paddingBottom: 92 },
  hero: { backgroundColor: '#162E4D', paddingHorizontal: 30, paddingTop: 64, paddingBottom: 28 },
  heroRow: { flexDirection: 'row', alignItems: 'center', gap: 14 },
  logoMark: { width: 40, height: 40, borderRadius: 14, alignItems: 'center', justifyContent: 'center' },
  heroEyebrow: { color: '#A7B9D0', fontSize: 13, fontWeight: '900', letterSpacing: 2 },
  heroTitle: { color: '#FFFFFF', fontSize: 25, fontWeight: '900', marginTop: 6 },
  hierarchyCard: { marginHorizontal: 26, marginTop: 26, borderRadius: 18, backgroundColor: '#FFFFFF', padding: 22, shadowColor: '#0F172A', shadowOpacity: 0.07, shadowOffset: { width: 0, height: 10 }, shadowRadius: 24, elevation: 4 },
  cardHead: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 },
  sectionLabel: { color: '#60799D', fontSize: 15, fontWeight: '900', letterSpacing: 2 },
  nodeCard: { minHeight: 90, borderRadius: 18, backgroundColor: '#FFFFFF', flexDirection: 'row', alignItems: 'center', gap: 14, padding: 16, shadowColor: '#0F172A', shadowOpacity: 0.05, shadowOffset: { width: 0, height: 8 }, shadowRadius: 20, elevation: 2 },
  nodeTall: { minHeight: 154, alignItems: 'flex-start', paddingTop: 22 },
  photoStub: { width: 56, height: 56, borderRadius: 28, borderWidth: 3, borderColor: '#9AA3B2', backgroundColor: '#F8FAFC' },
  nodeCopy: { flex: 1, minWidth: 0 },
  nameRow: { flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: 8 },
  nodeName: { color: '#07111F', fontSize: 17, lineHeight: 23, fontWeight: '900' },
  youBadge: { overflow: 'hidden', color: '#94A3B8', fontSize: 11, fontWeight: '900', paddingHorizontal: 8, paddingVertical: 5, borderRadius: 10, backgroundColor: '#F1F5F9' },
  accessBadge: { alignSelf: 'flex-start', overflow: 'hidden', fontSize: 12, fontWeight: '900', paddingHorizontal: 10, paddingVertical: 5, borderRadius: 11, marginTop: 5 },
  nodeOnline: { width: 17, height: 17, borderRadius: 9, backgroundColor: '#2DCB72', marginTop: 8 },
  actionWrap: { flexDirection: 'row', alignItems: 'center', gap: 8, flexWrap: 'wrap', justifyContent: 'flex-end' },
  callBtn: { height: 40, minWidth: 78, borderRadius: 20, backgroundColor: '#0EA5E9', flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6, paddingHorizontal: 14 },
  trackBtn: { height: 40, minWidth: 84, borderRadius: 20, backgroundColor: '#8B5CF6', flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6, paddingHorizontal: 14 },
  callText: { color: '#FFFFFF', fontSize: 15, fontWeight: '900' },
  downLine: { height: 54, alignItems: 'center', justifyContent: 'center' },
  statusHead: { marginHorizontal: 26, marginTop: 20, minHeight: 60, borderRadius: 17, backgroundColor: '#FFFFFF', flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 18, shadowColor: '#0F172A', shadowOpacity: 0.06, shadowOffset: { width: 0, height: 8 }, shadowRadius: 18, elevation: 3 },
  statusLeft: { flexDirection: 'row', alignItems: 'center', gap: 10, flex: 1 },
  statusTitle: { color: '#07111F', fontSize: 17, fontWeight: '900' },
  statusPill: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  statusPillText: { overflow: 'hidden', color: '#22C55E', fontSize: 12, fontWeight: '900', paddingHorizontal: 12, paddingVertical: 6, borderRadius: 13, backgroundColor: '#DCFCE7' },
  mapCard: { marginHorizontal: 26, marginTop: 20, borderRadius: 18, backgroundColor: '#FFFFFF', overflow: 'hidden', shadowColor: '#0F172A', shadowOpacity: 0.08, shadowOffset: { width: 0, height: 10 }, shadowRadius: 24, elevation: 4 },
  mapCanvas: { height: 250, backgroundColor: '#EAF4FF', overflow: 'hidden' },
  mapV: { position: 'absolute', top: 0, bottom: 0, width: 1, backgroundColor: '#D3E6FA' },
  mapH: { position: 'absolute', left: 0, right: 0, height: 1, backgroundColor: '#D3E6FA' },
  routeBubble: { position: 'absolute', left: 14, top: 14, overflow: 'hidden', color: '#1E293B', fontSize: 12, fontWeight: '900', paddingHorizontal: 14, paddingVertical: 8, borderRadius: 16, backgroundColor: '#FFFFFF' },
  updatedBubble: { position: 'absolute', left: 14, bottom: 18, overflow: 'hidden', color: '#64748B', fontSize: 12, fontWeight: '700', paddingHorizontal: 14, paddingVertical: 8, borderRadius: 16, backgroundColor: '#FFFFFF' },
  routeLine: { position: 'absolute', left: -8, right: 42, bottom: 66, height: 22, borderRadius: 12, backgroundColor: '#A6D0FF', transform: [{ rotate: '-20deg' }] },
  routeDot: { position: 'absolute', left: '55%', top: '52%', width: 28, height: 28, borderRadius: 14, borderWidth: 5, borderColor: '#BEE3FF', backgroundColor: '#0B84FF' },
  schoolBox: { position: 'absolute', right: 20, top: 37, width: 62, height: 50, borderRadius: 8, alignItems: 'center', justifyContent: 'center', backgroundColor: '#BBD9FF' },
  schoolText: { position: 'absolute', top: -16, color: '#3779DD', fontSize: 9, fontWeight: '900' },
  tree: { position: 'absolute', width: 30, height: 22, borderRadius: 14, backgroundColor: '#8BE2B6' },
  treeSmall: { position: 'absolute', width: 22, height: 18, borderRadius: 10, backgroundColor: '#77D9A6' },
  zoomControls: { position: 'absolute', right: 16, top: 94, width: 40, borderRadius: 20, backgroundColor: '#FFFFFF', overflow: 'hidden', shadowColor: '#0F172A', shadowOpacity: 0.12, shadowOffset: { width: 0, height: 6 }, shadowRadius: 12, elevation: 3 },
  zoomText: { height: 40, textAlign: 'center', textAlignVertical: 'center', color: '#07111F', fontSize: 22, fontWeight: '900' },
  zoomDivider: { height: 1, backgroundColor: '#E2E8F0' },
  routeSummary: { padding: 18 },
  routeSummaryHead: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  schoolRoute: { color: '#07111F', fontSize: 15, fontWeight: '900' },
  arrivedText: { color: '#22C55E', fontSize: 13, fontWeight: '900' },
  routeProgress: { height: 12, borderRadius: 6, backgroundColor: '#E2E8F0', overflow: 'hidden', marginTop: 10 },
  routeProgressFill: { width: '100%', height: 12, borderRadius: 6 },
  routeLegend: { flexDirection: 'row', justifyContent: 'space-between', marginTop: 12 },
  legendText: { color: '#64748B', fontSize: 12, fontWeight: '800' },
  addMember: { marginHorizontal: 26, marginTop: 22, minHeight: 64, borderRadius: 18, borderWidth: 1.4, borderStyle: 'dashed', borderColor: '#88CAFF', backgroundColor: '#EFF8FF', flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 10 },
  addMemberText: { color: '#0B84FF', fontSize: 17, fontWeight: '900' },
  sheetLayer: { ...StyleSheet.absoluteFillObject, justifyContent: 'flex-end' },
  sheetBackdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: 'rgba(15, 23, 42, 0.42)' },
  addSheet: { minHeight: 360, borderTopLeftRadius: 24, borderTopRightRadius: 24, backgroundColor: '#FFFFFF', paddingHorizontal: 23, paddingTop: 28, paddingBottom: 24 },
  sheetHead: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 18 },
  sheetTitle: { color: '#06122A', fontSize: 22, fontWeight: '900' },
  sheetClose: { width: 42, height: 42, borderRadius: 21, backgroundColor: '#F1F5F9', alignItems: 'center', justifyContent: 'center' },
  sheetPlusCircle: { alignSelf: 'center', width: 68, height: 68, borderRadius: 34, borderWidth: 1, borderStyle: 'dashed', borderColor: '#93C5FD', backgroundColor: '#EFF8FF', alignItems: 'center', justifyContent: 'center', marginBottom: 22 },
  sheetPlanText: { color: '#0F172A', fontSize: 16, fontWeight: '900', textAlign: 'center', marginBottom: 10 },
  sheetSubText: { color: '#7A8CA5', fontSize: 17, fontWeight: '700', textAlign: 'center' },
  sheetPrice: { color: '#0F172A', fontSize: 19, fontWeight: '900', textAlign: 'center', marginTop: 4, marginBottom: 28 },
  upgradeButton: { minHeight: 64, borderRadius: 15, backgroundColor: '#13B9F2', alignItems: 'center', justifyContent: 'center', shadowColor: '#0EA5E9', shadowOpacity: 0.16, shadowOffset: { width: 0, height: 12 }, shadowRadius: 24, elevation: 3 },
  upgradeText: { color: '#FFFFFF', fontSize: 20, fontWeight: '900' },
  notNowButton: { minHeight: 52, borderRadius: 14, backgroundColor: '#EEF2F7', alignItems: 'center', justifyContent: 'center', marginTop: 18 },
  notNowText: { color: '#7A8CA5', fontSize: 17, fontWeight: '900' },
});

// ===== GUARDIAN DASHBOARD =====
function GuardianDashboard() {
  const { user, logout } = useAuthStore();
  const [lovedOnes, setLovedOnes] = useState<any[]>([]);
  const [alerts, setAlerts] = useState<any[]>([]);
  const [sessions, setSessions] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [tab, setTab] = useState<'overview' | 'alerts' | 'history' | 'settings'>('overview');
  const [showLinkModal, setShowLinkModal] = useState(false);
  const [linkCode, setLinkCode] = useState('');
  const [linkLoading, setLinkLoading] = useState(false);
  const [linkError, setLinkError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      const [loRes, alRes, sesRes] = await Promise.all([
        guardianDashboardService.getLovedOnes().catch((err: any) => { console.log("LO ERROR:", err?.message, err?.response?.status); return { data: {} }; }),
        guardianDashboardService.getAlerts(20).catch(() => ({ data: [] })),
        guardianDashboardService.getSessions().catch(() => ({ data: [] })),
      ]);

      const loData = loRes.data || {};
      const monitored = loData.monitored_users || loData.loved_ones || [];
      setLovedOnes(Array.isArray(monitored) ? monitored : []);
      setAlerts(Array.isArray(alRes.data) ? alRes.data : alRes.data?.alerts || []);
      setSessions(Array.isArray(sesRes.data) ? sesRes.data : sesRes.data?.sessions || []);
    } catch (e: any) {
      console.log("FETCH_ERROR:", e?.message);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    const role = user?.role;
    if (role === 'guardian') {
      fetchData();
    }
  }, [user?.role]);

  useFocusEffect(
    React.useCallback(() => {
      if (user?.role === 'guardian') {
        fetchData();
      }
    }, [user?.role])
  );

  const onRefresh = async () => { setRefreshing(true); await fetchData(); setRefreshing(false); };

  const requestCheck = async (userId: string) => {
    try {
      await guardianDashboardService.requestCheck(userId);
      Alert.alert('Check Requested', 'A safety check has been sent to your loved one.');
    } catch (e: any) {
      Alert.alert('Error', e.response?.data?.detail || 'Failed to request check');
    }
  };

  const handleLinkChild = async () => {
    if (linkCode.length !== 6) { setLinkError('Enter a 6-digit code'); return; }
    setLinkLoading(true);
    setLinkError(null);
    try {
      await guardianLinkService.linkChild(linkCode);
      setShowLinkModal(false);
      setLinkCode('');
      setLinkError(null);
      fetchData();
    } catch (e: any) {
      const status = e.response?.status;
      if (status === 400) setLinkError('Code expired or invalid — try again');
      else if (status === 409) setLinkError('Child already linked');
      else if (status === 403) setLinkError('Cannot link from a child account');
      else setLinkError(e.response?.data?.detail || 'Something went wrong — try again');
    }
    setLinkLoading(false);
  };

  return (
    <SafeAreaView style={styles.safe} testID="guardian-dashboard">
      <ScrollView
        style={styles.scroll}
        contentContainerStyle={styles.content}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.primary} />}
      >
        <View style={styles.headerRow}>
          <View>
            <Text style={styles.title}>Family Safety</Text>
            <Text style={styles.subtitle}>Monitor your loved ones</Text>
            <ImpactBadge />
          </View>
          <TouchableOpacity onPress={logout} style={styles.logoutBtn} testID="logout-btn">
            <Ionicons name="log-out-outline" size={22} color={colors.textMuted} />
          </TouchableOpacity>
        </View>

        {/* Tabs */}
        <View style={styles.tabs}>
          {(['overview', 'alerts', 'history', 'settings'] as const).map((t) => (
            <TouchableOpacity
              key={t} style={[styles.tab, tab === t && styles.tabActive]}
              onPress={() => setTab(t)} testID={`guardian-tab-${t}`}
            >
              <Text style={[styles.tabText, tab === t && styles.tabTextActive]}>
                {t.charAt(0).toUpperCase() + t.slice(1)}
              </Text>
            </TouchableOpacity>
          ))}
        </View>

        {loading ? (
          <ActivityIndicator size="large" color={colors.primary} style={{ marginTop: spacing['4xl'] }} />
        ) : (
          <>
            {tab === 'overview' && (
              <>
                {/* Active Sessions */}
                {sessions.length > 0 && (
                  <>
                    <Text style={styles.sectionTitle}>Active Journeys</Text>
                    {sessions.map((s: any, i: number) => (
                      <View key={i} style={styles.sessionCard} testID={`session-card-${i}`}>
                        <View style={styles.liveRow}>
                          <View style={styles.liveDot} />
                          <Text style={styles.liveText}>LIVE</Text>
                        </View>
                        <Text style={styles.sessionId}>Session: {s.session_id?.slice(0, 12)}...</Text>
                        <Text style={styles.sessionTime}>Started: {formatTime(s.start_time)}</Text>
                      </View>
                    ))}
                  </>
                )}

                {/* Loved Ones */}
                <Text style={styles.sectionTitle}>Loved Ones</Text>
                {lovedOnes.length === 0 && (
                  <View style={styles.emptyCard} testID="empty-loved-ones">
                    <Ionicons name="people-outline" size={40} color={colors.textMuted} />
                    <Text style={styles.emptyText}>No linked loved ones yet</Text>
                    {!showLinkModal ? (
                      <TouchableOpacity
                        style={styles.linkButton}
                        onPress={() => setShowLinkModal(true)}
                        testID="link-child-btn"
                      >
                        <Ionicons name="link" size={18} color={colors.white} />
                        <Text style={styles.linkButtonText}>Link a Child</Text>
                      </TouchableOpacity>
                    ) : (
                      <View style={styles.linkInputWrap} testID="link-input-section">
                        <TextInput
                          style={styles.linkInput}
                          value={linkCode}
                          onChangeText={(t) => { setLinkCode(t.replace(/\D/g, '').slice(0, 6)); setLinkError(null); }}
                          placeholder="Enter 6-digit code"
                          placeholderTextColor={colors.textMuted}
                          keyboardType="numeric"
                          maxLength={6}
                          testID="link-code-input"
                        />
                        <View style={styles.linkBtnRow}>
                          <TouchableOpacity style={styles.linkCancelBtn} onPress={() => { setShowLinkModal(false); setLinkCode(''); setLinkError(null); }}>
                            <Text style={styles.linkCancelText}>Cancel</Text>
                          </TouchableOpacity>
                          <TouchableOpacity
                            style={[styles.linkSubmitBtn, linkLoading && { opacity: 0.5 }]}
                            onPress={handleLinkChild}
                            disabled={linkLoading}
                            testID="link-submit-btn"
                          >
                            <Text style={styles.linkSubmitText}>{linkLoading ? 'Linking...' : 'Link'}</Text>
                          </TouchableOpacity>
                        </View>
                        {linkError && <Text style={styles.linkError} testID="link-error-text">{linkError}</Text>}
                      </View>
                    )}
                  </View>
                )}

                {lovedOnes.length > 0 && (
                  <>
                    {/* Secondary link action when list is populated */}
                    {!showLinkModal ? (
                      <TouchableOpacity
                        style={styles.linkSecondaryBtn}
                        onPress={() => { setShowLinkModal(true); setLinkError(null); }}
                        testID="link-child-secondary-btn"
                      >
                        <Ionicons name="add-circle-outline" size={16} color={colors.primary} />
                        <Text style={styles.linkSecondaryText}>Link a Child</Text>
                      </TouchableOpacity>
                    ) : (
                      <View style={[styles.linkInputWrap, { marginBottom: spacing.md }]} testID="link-input-section-secondary">
                        <TextInput
                          style={styles.linkInput}
                          value={linkCode}
                          onChangeText={(t) => { setLinkCode(t.replace(/\D/g, '').slice(0, 6)); setLinkError(null); }}
                          placeholder="Enter 6-digit code"
                          placeholderTextColor={colors.textMuted}
                          keyboardType="numeric"
                          maxLength={6}
                          testID="link-code-input-secondary"
                        />
                        <View style={styles.linkBtnRow}>
                          <TouchableOpacity style={styles.linkCancelBtn} onPress={() => { setShowLinkModal(false); setLinkCode(''); setLinkError(null); }}>
                            <Text style={styles.linkCancelText}>Cancel</Text>
                          </TouchableOpacity>
                          <TouchableOpacity
                            style={[styles.linkSubmitBtn, linkLoading && { opacity: 0.5 }]}
                            onPress={handleLinkChild}
                            disabled={linkLoading}
                            testID="link-submit-btn-secondary"
                          >
                            <Text style={styles.linkSubmitText}>{linkLoading ? 'Linking...' : 'Link'}</Text>
                          </TouchableOpacity>
                        </View>
                        {linkError && <Text style={styles.linkError}>{linkError}</Text>}
                      </View>
                    )}

                    {lovedOnes.map((person: any, i: number) => {
                      const statusCfg = getStatusBadge(person.status);
                      return (
                        <View key={i} style={[styles.personCard, person.status === 'EMERGENCY' && styles.personCardEmergency]} testID={`loved-one-${i}`}>
                          <View style={[styles.personAvatar, { backgroundColor: statusCfg.color + '20' }]}>
                            <Ionicons name="person" size={24} color={statusCfg.color} />
                          </View>
                          <View style={styles.personInfo}>
                            <Text style={styles.personName}>{person.name || person.full_name || 'User'}</Text>
                            <View style={[styles.statusPill, { backgroundColor: statusCfg.bg }]} testID={`status-badge-${i}`}>
                              <View style={[styles.statusDot, { backgroundColor: statusCfg.color }]} />
                              <Text style={[styles.statusLabel, { color: statusCfg.color }]}>{statusCfg.label}</Text>
                            </View>
                            <LocationIndicator locationType={person.location_type} lastUpdated={person.last_updated} testID={`location-${i}`} />
                          </View>
                          <TouchableOpacity
                            style={styles.checkBtn}
                            onPress={() => requestCheck(person.user_id || person.id)}
                            testID={`check-btn-${i}`}
                          >
                            <Text style={styles.checkBtnText}>Check In</Text>
                          </TouchableOpacity>
                        </View>
                      );
                    })}
                  </>
                )}
              </>
            )}

            {tab === 'alerts' && (
              <>
                <Text style={styles.sectionTitle}>Recent Alerts</Text>
                {alerts.length === 0 ? (
                  <View style={styles.emptyCard}>
                    <Ionicons name="shield-checkmark" size={40} color={colors.safe} />
                    <Text style={styles.emptyText}>No alerts</Text>
                  </View>
                ) : (
                  alerts.map((alert: any, i: number) => (
                    <View key={i} style={styles.alertCard} testID={`alert-item-${i}`}>
                      <View style={[styles.alertDot, { backgroundColor: riskColor(alert.severity || 'moderate') }]} />
                      <View style={styles.alertInfo}>
                        <Text style={styles.alertType}>{alert.type || 'Alert'}</Text>
                        <Text style={styles.alertTime}>{formatTime(alert.created_at || alert.timestamp)}</Text>
                      </View>
                    </View>
                  ))
                )}
              </>
            )}

            {tab === 'history' && (
              <>
                <Text style={styles.sectionTitle}>Journey History</Text>
                <HistorySection />
              </>
            )}

            {tab === 'settings' && (
              <View style={styles.settingsSection}>
                <Text style={styles.sectionTitle}>Account</Text>
                <View style={styles.settingCard}>
                  <Ionicons name="person" size={20} color={colors.primary} />
                  <Text style={styles.settingLabel}>{user?.full_name || 'User'}</Text>
                </View>
                <View style={styles.settingCard}>
                  <Ionicons name="mail" size={20} color={colors.primary} />
                  <Text style={styles.settingLabel}>{user?.email || ''}</Text>
                </View>
                <View style={styles.settingCard}>
                  <Ionicons name="shield" size={20} color={colors.primary} />
                  <Text style={styles.settingLabel}>Role: {user?.role}</Text>
                </View>
                <TouchableOpacity
                  style={styles.logoutFullBtn}
                  onPress={logout}
                  testID="settings-logout-btn"
                >
                  <Ionicons name="log-out" size={20} color={colors.critical} />
                  <Text style={styles.logoutFullText}>Sign Out</Text>
                </TouchableOpacity>
              </View>
            )}
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

function HistorySection() {
  const [history, setHistory] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    guardianDashboardService.getHistory()
      .then((res) => setHistory(Array.isArray(res.data) ? res.data : res.data?.sessions || []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <ActivityIndicator color={colors.primary} />;
  if (history.length === 0) {
    return (
      <View style={styles.emptyCard}>
        <Ionicons name="time-outline" size={40} color={colors.textMuted} />
        <Text style={styles.emptyText}>No journey history</Text>
      </View>
    );
  }

  return (
    <>
      {history.map((h: any, i: number) => (
        <View key={i} style={styles.historyCard} testID={`history-item-${i}`}>
          <Ionicons name="navigate-circle" size={20} color={colors.primary} />
          <View style={styles.historyInfo}>
            <Text style={styles.historyId}>{h.session_id?.slice(0, 12)}...</Text>
            <Text style={styles.historyTime}>
              {formatTime(h.start_time)} — {h.end_time ? formatTime(h.end_time) : 'ongoing'}
            </Text>
          </View>
          <Text style={[styles.historyStatus, { color: h.status === 'completed' ? colors.safe : colors.warning }]}>
            {h.status || 'unknown'}
          </Text>
        </View>
      ))}
    </>
  );
}

// ===== SHARE SAFETY =====
function ShareSafety() {
  const { user, logout } = useAuthStore();
  const [score, setScore] = useState<any>(null);

  useEffect(() => {
    safetyScoreService.getLocationScore(12.9716, 77.5946)
      .then(res => setScore(res.data))
      .catch(() => {});
  }, []);

  const shareMyStatus = async () => {
    try {
      const res = await locationShareService.createShare(4);
      const trackingUrl = `https://nischint.care${res.data.tracking_url}`;
      const s = score?.score?.toFixed(1) || '?';
      await Share.share({
        message: `Track my live location on NISCHINT:\n${trackingUrl}\n\nArea safety score: ${s}/10 (${scoreLabel(score?.score || 0)})`,
      });
    } catch {
      const s = score?.score?.toFixed(1) || '?';
      await Share.share({
        message: `I'm using NISCHINT for safety monitoring. My current area safety score: ${s}/10 (${scoreLabel(score?.score || 0)}). Stay safe! nischint.care`,
      });
    }
  };

  return (
    <SafeAreaView style={styles.safe} testID="share-safety-screen">
      <ScrollView style={styles.scroll} contentContainerStyle={styles.content}>
        <View style={styles.headerRow}>
          <View>
            <Text style={styles.title}>Share Safety</Text>
            <Text style={styles.subtitle}>Let your network know you're safe</Text>
          </View>
          <TouchableOpacity onPress={logout} style={styles.logoutBtn} testID="logout-btn">
            <Ionicons name="log-out-outline" size={22} color={colors.textMuted} />
          </TouchableOpacity>
        </View>

        {/* Share Card */}
        <View style={styles.shareCard} testID="share-card">
          <View style={styles.shareLogo}>
            <Ionicons name="shield-checkmark" size={32} color={colors.primary} />
          </View>
          <Text style={styles.shareTitle}>NISCHINT</Text>
          {score && (
            <>
              <View style={[styles.shareScoreCircle, { borderColor: scoreColor(score.score) }]}>
                <Text style={[styles.shareScoreNum, { color: scoreColor(score.score) }]}>
                  {score.score.toFixed(1)}
                </Text>
                <Text style={styles.shareScoreOf}>/10</Text>
              </View>
              <Text style={[styles.shareLabel, { color: scoreColor(score.score) }]}>
                {scoreLabel(score.score)}
              </Text>
            </>
          )}
          <TouchableOpacity style={styles.shareSendBtn} onPress={shareMyStatus} testID="share-send-btn">
            <Ionicons name="share-social" size={20} color={colors.white} />
            <Text style={styles.shareSendText}>Share My Safety Status</Text>
          </TouchableOpacity>
        </View>

        {/* Guardian Management */}
        <Text style={styles.sectionTitle}>Your Guardians</Text>
        <View style={styles.emptyCard}>
          <Ionicons name="people-outline" size={40} color={colors.textMuted} />
          <Text style={styles.emptyText}>Guardian management coming soon</Text>
          <Text style={styles.emptyDesc}>Add trusted contacts who will receive your safety updates</Text>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

// ===== HELPERS =====
function relativeTime(isoStr: string | null): string {
  if (!isoStr) return '';
  const diff = Date.now() - new Date(isoStr).getTime();
  const sec = Math.floor(diff / 1000);
  if (sec < 60) return 'just now';
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  return `${Math.floor(hr / 24)}d ago`;
}

function getStatusBadge(status: string | null): { label: string; color: string; bg: string } {
  const s = (status || '').toUpperCase();
  if (s === 'EMERGENCY') return { label: 'EMERGENCY', color: '#EF4444', bg: '#EF444420' };
  if (s === 'LIVE_JOURNEY') return { label: 'Live Journey', color: '#3B82F6', bg: '#3B82F620' };
  if (s === 'CHECK_IN_PENDING') return { label: 'Check-in Pending', color: '#F59E0B', bg: '#F59E0B20' };
  if (s === 'HELP') return { label: 'Needs Help', color: '#EF4444', bg: '#EF444420' };
  return { label: 'Safe', color: '#22C55E', bg: '#22C55E20' };
}

function LocationIndicator({ locationType, lastUpdated, testID }: { locationType: string | null; lastUpdated: string | null; testID?: string }) {
  let dotColor = '#9CA3AF';
  let label = 'Location unavailable';
  if (locationType === 'live') { dotColor = '#22C55E'; label = 'Live'; }
  else if (locationType === 'emergency') { dotColor = '#EF4444'; label = 'Emergency location'; }
  else if (locationType === 'recent') { dotColor = '#F59E0B'; label = `Last seen · ${relativeTime(lastUpdated)}`; }
  else if (locationType === 'historical') { dotColor = '#9CA3AF'; label = `Last known · ${relativeTime(lastUpdated)}`; }
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: 5, marginTop: 3 }} testID={testID}>
      {locationType && <View style={{ width: 7, height: 7, borderRadius: 3.5, backgroundColor: dotColor }} />}
      <Text style={{ fontSize: 11, color: colors.textSecondary }}>{label}</Text>
    </View>
  );
}

function formatTime(ts: string | null) {
  if (!ts) return '--';
  return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.bg },
  scroll: { flex: 1 },
  content: { padding: spacing.xl, paddingBottom: spacing['5xl'] },
  headerRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: spacing.lg },
  title: { fontSize: fontSize['2xl'], fontWeight: '800', color: colors.textPrimary },
  subtitle: { fontSize: fontSize.sm, color: colors.textSecondary },
  logoutBtn: { padding: spacing.sm },
  tabs: { flexDirection: 'row', gap: spacing.xs, marginBottom: spacing.xl },
  tab: { flex: 1, paddingVertical: spacing.sm, borderRadius: radius.lg, backgroundColor: colors.bgCard, alignItems: 'center', borderWidth: 1, borderColor: colors.border },
  tabActive: { backgroundColor: colors.primary + '20', borderColor: colors.primary },
  tabText: { fontSize: fontSize.xs, fontWeight: '600', color: colors.textMuted },
  tabTextActive: { color: colors.primary },
  sectionTitle: { fontSize: fontSize.lg, fontWeight: '700', color: colors.textPrimary, marginBottom: spacing.md, marginTop: spacing.lg },
  sessionCard: { backgroundColor: colors.bgCard, borderRadius: radius.lg, padding: spacing.lg, borderWidth: 1, borderColor: colors.safe + '30', marginBottom: spacing.md },
  liveRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, marginBottom: spacing.sm },
  liveDot: { width: 8, height: 8, borderRadius: 4, backgroundColor: colors.safe },
  liveText: { fontSize: fontSize.xs, fontWeight: '800', color: colors.safe, letterSpacing: 2 },
  sessionId: { fontSize: fontSize.sm, fontWeight: '600', color: colors.textPrimary },
  sessionTime: { fontSize: fontSize.xs, color: colors.textMuted, marginTop: 2 },
  personCard: { flexDirection: 'row', alignItems: 'center', backgroundColor: colors.bgCard, borderRadius: radius.lg, padding: spacing.lg, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.md },
  personAvatar: { width: 44, height: 44, borderRadius: 22, backgroundColor: colors.primary + '20', justifyContent: 'center', alignItems: 'center', marginRight: spacing.md },
  personInfo: { flex: 1 },
  personName: { fontSize: fontSize.md, fontWeight: '700', color: colors.textPrimary },
  personStatus: { fontSize: fontSize.sm, color: colors.safe, marginTop: 2 },
  checkBtn: { backgroundColor: colors.primary + '20', paddingHorizontal: spacing.lg, paddingVertical: spacing.sm, borderRadius: radius.full },
  checkBtnText: { fontSize: fontSize.sm, fontWeight: '600', color: colors.primary },
  emptyCard: { backgroundColor: colors.bgCard, borderRadius: radius.xl, padding: spacing['3xl'], alignItems: 'center', gap: spacing.sm, borderWidth: 1, borderColor: colors.border },
  emptyText: { fontSize: fontSize.md, color: colors.textMuted },
  emptyDesc: { fontSize: fontSize.sm, color: colors.textMuted, textAlign: 'center' },
  alertCard: { flexDirection: 'row', alignItems: 'center', backgroundColor: colors.bgCard, borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.sm },
  alertDot: { width: 8, height: 8, borderRadius: 4, marginRight: spacing.md },
  alertInfo: { flex: 1 },
  alertType: { fontSize: fontSize.sm, fontWeight: '600', color: colors.textPrimary, textTransform: 'capitalize' },
  alertTime: { fontSize: fontSize.xs, color: colors.textMuted },
  historyCard: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, backgroundColor: colors.bgCard, borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.sm },
  historyInfo: { flex: 1 },
  historyId: { fontSize: fontSize.sm, fontWeight: '600', color: colors.textPrimary },
  historyTime: { fontSize: fontSize.xs, color: colors.textMuted },
  historyStatus: { fontSize: fontSize.xs, fontWeight: '700', textTransform: 'capitalize' },
  settingsSection: { gap: spacing.md },
  settingCard: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, backgroundColor: colors.bgCard, borderRadius: radius.md, padding: spacing.lg, borderWidth: 1, borderColor: colors.border },
  settingLabel: { fontSize: fontSize.md, color: colors.textPrimary },
  logoutFullBtn: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: spacing.sm, backgroundColor: colors.critical + '15', borderRadius: radius.lg, padding: spacing.lg, marginTop: spacing.xl, borderWidth: 1, borderColor: colors.critical + '30' },
  logoutFullText: { fontSize: fontSize.md, fontWeight: '700', color: colors.critical },
  shareCard: { backgroundColor: colors.bgCard, borderRadius: radius.xl, padding: spacing['3xl'], alignItems: 'center', borderWidth: 1, borderColor: colors.border, ...shadows.lg, marginTop: spacing.lg },
  shareLogo: { marginBottom: spacing.md },
  shareTitle: { fontSize: fontSize.xl, fontWeight: '800', color: colors.textPrimary, letterSpacing: 3, marginBottom: spacing.xl },
  shareScoreCircle: { width: 100, height: 100, borderRadius: 50, borderWidth: 4, justifyContent: 'center', alignItems: 'center', backgroundColor: colors.bgElevated, marginBottom: spacing.md },
  shareScoreNum: { fontSize: fontSize['3xl'], fontWeight: '900' },
  shareScoreOf: { fontSize: fontSize.xs, color: colors.textMuted, marginTop: -4 },
  shareLabel: { fontSize: fontSize.lg, fontWeight: '700', marginBottom: spacing.xl },
  shareSendBtn: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, backgroundColor: colors.primary, borderRadius: radius.full, paddingHorizontal: spacing['2xl'], paddingVertical: spacing.md },
  shareSendText: { color: colors.white, fontSize: fontSize.md, fontWeight: '700' },
  linkButton: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, backgroundColor: colors.primary, paddingHorizontal: spacing.xl, paddingVertical: spacing.md, borderRadius: radius.lg, marginTop: spacing.md },
  linkButtonText: { fontSize: fontSize.md, fontWeight: '700', color: colors.white },
  linkSecondaryBtn: { flexDirection: 'row', alignItems: 'center', gap: spacing.xs, alignSelf: 'flex-end', paddingVertical: spacing.xs, marginBottom: spacing.sm },
  linkSecondaryText: { fontSize: fontSize.sm, fontWeight: '600', color: colors.primary },
  linkInputWrap: { width: '100%', backgroundColor: colors.bgCard, borderRadius: radius.lg, padding: spacing.lg, borderWidth: 1, borderColor: colors.border, gap: spacing.sm, marginTop: spacing.sm },
  linkInput: { backgroundColor: colors.bgElevated, borderRadius: radius.lg, paddingHorizontal: spacing.lg, paddingVertical: spacing.md, fontSize: 24, fontWeight: '700', color: colors.textPrimary, textAlign: 'center', letterSpacing: 8, borderWidth: 1, borderColor: colors.border },
  linkBtnRow: { flexDirection: 'row', gap: spacing.md },
  linkCancelBtn: { flex: 1, paddingVertical: spacing.md, alignItems: 'center', borderRadius: radius.lg, backgroundColor: colors.bgElevated, borderWidth: 1, borderColor: colors.border },
  linkCancelText: { fontSize: fontSize.md, fontWeight: '600', color: colors.textMuted },
  linkSubmitBtn: { flex: 1, paddingVertical: spacing.md, alignItems: 'center', borderRadius: radius.lg, backgroundColor: colors.primary },
  linkSubmitText: { fontSize: fontSize.md, fontWeight: '700', color: colors.white },
  linkError: { fontSize: fontSize.sm, color: '#EF4444', textAlign: 'center' },
  statusPill: { flexDirection: 'row', alignItems: 'center', gap: 4, paddingHorizontal: 8, paddingVertical: 2, borderRadius: 20, alignSelf: 'flex-start', marginTop: 3 },
  statusDot: { width: 6, height: 6, borderRadius: 3 },
  statusLabel: { fontSize: 11, fontWeight: '700' },
  personCardEmergency: { borderColor: '#EF444460', borderWidth: 2, backgroundColor: '#EF444410' },
});
