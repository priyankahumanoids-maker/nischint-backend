// Home — role-based dashboard router
import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, Pressable,
  RefreshControl, Alert, TextInput, Modal, Vibration, Animated, Share,
  Linking, Platform, AppState, useWindowDimensions,
} from 'react-native';
import * as Location from 'expo-location';
import { SafeAreaView } from 'react-native-safe-area-context';
import { LinearGradient } from 'expo-linear-gradient';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import Svg, { Circle } from 'react-native-svg';
import NetInfo from '@react-native-community/netinfo';
import { useAuthStore } from '@/stores/authStore';
import { useEmergencyStore } from '@/stores/emergencyStore';
import { safetyScoreService, guardianService, guardianDashboardService, checkInService, locationShareService, childLinkService, guardianLinkService } from '@/services/endpoints';
import { triggerSilentSOS, cancelSOS } from '@/services/deviceSafety';
import { emergencyService } from '@/services/emergency';
import { useGuardianSSE } from '@/hooks/useGuardianSSE';
import { useChildSSE } from '@/hooks/useChildSSE';
import { useGuardianLocationPolling } from '@/hooks/useGuardianLocationPolling';
import { GuardianLiveMap } from '@/components/GuardianLiveMap';
import { RiskOverlayMap } from '@/components/RiskOverlayMap';
import EscalationTracker from '@/components/EscalationTracker';
import { SafetyServicesStatus } from '@/components/SafetyServicesStatus';
import { WearableConnectCard } from '@/components/wearable/WearableConnectCard';
import { VitalsStrip } from '@/components/wearable/VitalsStrip';
import { DependentVitalsCard } from '@/components/wearable/DependentVitalsCard';
import { FeedbackPrompt, type FeedbackPromptHandle } from '@/components/safety/FeedbackPrompt';
import { useLiveTrackingStore } from '@/stores/liveTrackingStore';
import { useRiskStore } from '@/stores/riskStore';
import type { ChildLocation } from '@/stores/liveTrackingStore';
import { resolveAlertState, mergeAlertSources, type UnifiedAlert, type AlertState } from '@/services/alertResolver';
import { useAlertStore } from '@/stores/alertStore';
import { colors, spacing, fontSize, radius, shadows, scoreColor, scoreLabel, riskColor } from '@/theme';
import { toIST } from '@/lib/timeUtils';

const BADGE: Record<string, { label: string; icon: keyof typeof Ionicons.glyphMap }> = {
  child:    { label: 'Kids Safety',   icon: 'happy-outline' },
  guardian: { label: 'Parents Care',  icon: 'heart-outline' },
  woman:    { label: 'Women Safety',  icon: 'shield-half-outline' },
  parent:   { label: 'Parents Care',  icon: 'heart-outline' },
  caregiver:{ label: 'Parents Care',  icon: 'heart-outline' },
  operator: { label: 'Command Center',icon: 'headset-outline' },
  admin:    { label: 'Admin',         icon: 'settings-outline' },
};

const HIDDEN_TAP_COUNT = 5;
const HIDDEN_TAP_WINDOW = 3000;

// Module-scoped dedup set for `risk_update` SSE events. Survives
// component re-mounts (e.g. tab switches) so a recent reconnect that
// re-delivers replay events can't double-apply them. Bounded LRU-style
// in the handler.
const _seenRiskEmitKeys = new Set<string>();
const AnimatedCircle = Animated.createAnimatedComponent(Circle);

export default function HomeScreen() {
  return <LegacyHomeScreen />;
}

function ReferenceProtectedDashboard({ mode }: { mode: string }) {
  const [showSOSFlow, setShowSOSFlow] = useState(false);
  const config = {
    kids: { name: 'Priya', role: 'Child - Protected', badge: 'Child', primary: 'Daughter', secondary: 'Rajesh', secondaryRole: 'Guardian', action: 'Start Safe Walk', actionSub: 'Journey protection' },
    women: { name: 'XSXS', role: 'Woman - Protected', badge: 'Woman', primary: 'Priya', secondary: 'Rajesh', primaryRole: 'Mother', secondaryRole: 'Father', action: 'Start Safe Walk', actionSub: 'Journey protection' },
    senior: { name: 'ZCVCV', role: 'Senior Citizen - Protected', badge: 'Senior', primary: 'Priya', secondary: 'Rajesh', primaryRole: 'Daughter', secondaryRole: 'Son', action: 'Medicine', actionSub: 'Health reminder' },
    family: { name: 'Family Member', role: 'Protected Member', badge: 'Family', primary: 'Mom', secondary: 'Dad', primaryRole: 'Co-Parent', secondaryRole: 'Co-Parent', action: 'Safe Walk', actionSub: 'Route protection' },
  }[mode] || { name: 'Protected Member', role: 'AI Protected', badge: 'Safe', primary: 'Priya', secondary: 'Rajesh', primaryRole: 'Guardian', secondaryRole: 'Guardian', action: 'Safe Walk', actionSub: 'Route protection' };

  return (
    <SafeAreaView style={protectedHome.safe} edges={['top']}>
      <ScrollView style={protectedHome.scroll} contentContainerStyle={protectedHome.content} showsVerticalScrollIndicator={false}>
        <View style={protectedHome.topStatus}>
          <Text style={protectedHome.statusText}>You Are Protected - AI Active - Guardian Connected</Text>
        </View>

        <View style={protectedHome.profileHead}>
          <View>
            <Text style={protectedHome.personName}>{config.name}</Text>
            <Text style={protectedHome.personRole}>{config.role}</Text>
          </View>
          <Text style={protectedHome.roleBadge}>{config.badge}</Text>
        </View>

        <View style={protectedHome.guardianRow}>
          <View style={protectedHome.guardianCard}>
            <View style={protectedHome.avatarCircle}><Ionicons name="person" size={24} color="#1F2937" /></View>
            <Text style={protectedHome.guardianName}>{config.primary}</Text>
            <Text style={protectedHome.guardianRole}>{config.primaryRole}</Text>
            <TouchableOpacity style={protectedHome.callGreen} activeOpacity={0.84}>
              <Ionicons name="call-outline" size={15} color="#FFFFFF" />
              <Text style={protectedHome.callText}>Call</Text>
            </TouchableOpacity>
          </View>
          <View style={protectedHome.guardianCard}>
            <View style={protectedHome.avatarCircle}><Ionicons name="person" size={24} color="#1F2937" /></View>
            <Text style={protectedHome.guardianName}>{config.secondary}</Text>
            <Text style={protectedHome.guardianRole}>{config.secondaryRole}</Text>
            <TouchableOpacity style={protectedHome.callBlue} activeOpacity={0.84}>
              <Ionicons name="call-outline" size={15} color="#FFFFFF" />
              <Text style={protectedHome.callText}>Call</Text>
            </TouchableOpacity>
          </View>
        </View>

        <TouchableOpacity style={protectedHome.safeWalkBtn} activeOpacity={0.86}>
          <Ionicons name="walk-outline" size={18} color="#FFFFFF" />
          <View>
            <Text style={protectedHome.safeWalkText}>{config.action}</Text>
            <Text style={protectedHome.safeWalkSub}>{config.actionSub}</Text>
          </View>
        </TouchableOpacity>

        <TouchableOpacity style={protectedHome.sosCard} activeOpacity={0.9} onPress={() => setShowSOSFlow(true)}>
          <Ionicons name="alert-circle" size={42} color="#FFFFFF" />
          <Text style={protectedHome.sosTitle}>I NEED HELP</Text>
          <Text style={protectedHome.sosSub}>Tap anywhere - Hold 2 seconds</Text>
          <Text style={protectedHome.sosLine}>Guardian notified instantly</Text>
          <Text style={protectedHome.sosLine}>Live location shared</Text>
          <Text style={protectedHome.sosLine}>AI emergency monitoring activated</Text>
        </TouchableOpacity>

        <View style={protectedHome.actionPair}>
          <TouchableOpacity style={protectedHome.safeButton} activeOpacity={0.86}>
            <Text style={protectedHome.safeButtonText}>I'm Safe</Text>
          </TouchableOpacity>
          <TouchableOpacity style={protectedHome.etaButton} activeOpacity={0.86}>
            <Text style={protectedHome.safeButtonText}>ETA Share</Text>
          </TouchableOpacity>
        </View>

        <View style={protectedHome.sectionCard}>
          <Text style={protectedHome.sectionTitle}>Protection Status</Text>
          <Text style={protectedHome.sectionSub}>AI monitoring systems active</Text>
          <View style={protectedHome.segmentRow}>
            <Text style={protectedHome.segmentOn}>Monitoring</Text>
            <Text style={protectedHome.segmentOff}>Devices</Text>
            <Text style={protectedHome.segmentOff}>Permissions</Text>
          </View>
          {['Emergency Alert', 'Guardian Alerts', 'Route Monitoring'].map((item) => (
            <View key={item} style={protectedHome.toggleRow}>
              <Text style={protectedHome.toggleText}>{item}</Text>
              <View style={protectedHome.toggleOn}><View style={protectedHome.toggleKnob} /></View>
            </View>
          ))}
        </View>

        <View style={protectedHome.routeCard}>
          <Text style={protectedHome.sectionTitle}>My Routes</Text>
          <Text style={protectedHome.sectionSub}>2 routes monitored</Text>
          <View style={protectedHome.routeItem}>
            <Ionicons name="navigate-circle-outline" size={26} color="#22C55E" />
            <View style={{ flex: 1 }}>
              <Text style={protectedHome.routeTitle}>Home - School</Text>
              <Text style={protectedHome.routeMeta}>4.2 km - 32 min - Safe</Text>
            </View>
            <Text style={protectedHome.arrived}>Arrived</Text>
          </View>
          <View style={protectedHome.routeItem}>
            <Ionicons name="warning-outline" size={26} color="#F59E0B" />
            <View style={{ flex: 1 }}>
              <Text style={protectedHome.routeTitle}>School - Home</Text>
              <Text style={protectedHome.routeMeta}>4.2 km - Waiting</Text>
            </View>
            <Text style={protectedHome.pending}>Pending</Text>
          </View>
        </View>
      </ScrollView>
      <ProtectedSOSFlow visible={showSOSFlow} onClose={() => setShowSOSFlow(false)} />
    </SafeAreaView>
  );
}

type ProtectedSOSPhase = 'countdown' | 'activating' | 'active';

function ProtectedSOSFlow({
  visible,
  onClose,
  triggerSource = 'protected_sos_card',
  startPhase = 'countdown',
}: {
  visible: boolean;
  onClose: () => void;
  triggerSource?: string;
  startPhase?: ProtectedSOSPhase;
}) {
  const { height } = useWindowDimensions();
  const [phase, setPhase] = useState<ProtectedSOSPhase>(startPhase);
  const [count, setCount] = useState(3);
  const { activate, deactivate } = useEmergencyStore();
  const pulse = useRef(new Animated.Value(1)).current;
  const ringProgress = useRef(new Animated.Value(0)).current;
  const countScale = useRef(new Animated.Value(1)).current;
  const actionReveal = useRef(Array.from({ length: 6 }, () => new Animated.Value(0))).current;
  const timelineReveal = useRef(new Animated.Value(0)).current;
  const activationStarted = useRef(false);
  const ringRadius = 70;
  const ringCircumference = 2 * Math.PI * ringRadius;
  const ringDashOffset = ringProgress.interpolate({
    inputRange: [0, 1],
    outputRange: [0, ringCircumference],
  });
  const checklist = [
    ['people-outline', 'Parent Notified', '#008CFF'],
    ['people-outline', 'Co-Parent Notified', '#008CFF'],
    ['notifications-outline', 'Emergency Contacts Notified', '#F59E0B'],
    ['location-outline', 'Live Location Shared', '#22C55E'],
    ['time-outline', 'Emergency Timeline Started', '#00A8FF'],
    ['shield-checkmark-outline', 'Emergency Monitoring Activated', '#4ADE80'],
  ] as const;

  useEffect(() => {
    if (!visible) {
      setPhase(startPhase);
      setCount(3);
      ringProgress.stopAnimation();
      ringProgress.setValue(0);
      pulse.stopAnimation();
      pulse.setValue(1);
      countScale.setValue(1);
      timelineReveal.setValue(0);
      actionReveal.forEach((anim) => anim.setValue(0));
      activationStarted.current = false;
      return;
    }
    setPhase(startPhase);
    setCount(3);
    ringProgress.setValue(0);
    countScale.setValue(1);
    timelineReveal.setValue(0);
    actionReveal.forEach((anim) => anim.setValue(0));
    activationStarted.current = false;
    Vibration.vibrate([0, 80, 60, 80]);
    if (startPhase === 'countdown') {
      Animated.timing(ringProgress, {
        toValue: 1,
        duration: 2400,
        useNativeDriver: false,
      }).start();
    }
  }, [visible, startPhase, ringProgress, countScale, timelineReveal, pulse, actionReveal]);

  useEffect(() => {
    if (!visible || phase !== 'countdown') return;
    Animated.sequence([
      Animated.timing(countScale, { toValue: 1.18, duration: 120, useNativeDriver: true }),
      Animated.timing(countScale, { toValue: 1, duration: 220, useNativeDriver: true }),
    ]).start();

    if (count > 1) {
      const timer = setTimeout(() => setCount((value) => value - 1), 800);
      return () => clearTimeout(timer);
    }

    const timer = setTimeout(() => setPhase('activating'), 800);
    return () => clearTimeout(timer);
  }, [visible, phase, count, countScale]);

  useEffect(() => {
    if (!visible || phase !== 'activating' || activationStarted.current) return;
    activationStarted.current = true;
    let cancelled = false;
    const loop = Animated.loop(Animated.sequence([
      Animated.timing(pulse, { toValue: 1.12, duration: 300, useNativeDriver: true }),
      Animated.timing(pulse, { toValue: 0.94, duration: 300, useNativeDriver: true }),
    ]));
    loop.start();

    const activateSOS = async () => {
      try {
        const result = await triggerSilentSOS('1234', triggerSource);
        const eventId = result.eventId || `local-sos-${Date.now()}`;
        if (result.success) {
          await activate(eventId, triggerSource);
        }
      } catch {
        // The emergency UI still confirms locally if network/API delivery is delayed.
      }
    };

    activateSOS();
    const timer = setTimeout(() => {
      if (!cancelled) setPhase('active');
    }, 1200);
    return () => {
      cancelled = true;
      clearTimeout(timer);
      loop.stop();
    };
  }, [visible, phase, activate, triggerSource, pulse]);

  useEffect(() => {
    if (!visible || phase !== 'active') return;
    pulse.setValue(1);
    const loop = Animated.loop(Animated.sequence([
      Animated.timing(pulse, { toValue: 1.16, duration: 850, useNativeDriver: true }),
      Animated.timing(pulse, { toValue: 1, duration: 850, useNativeDriver: true }),
    ]));
    loop.start();
    Animated.stagger(145, actionReveal.map((anim) => Animated.timing(anim, {
      toValue: 1,
      duration: 360,
      useNativeDriver: true,
    }))).start();
    Animated.timing(timelineReveal, {
      toValue: 1,
      duration: 320,
      delay: 900,
      useNativeDriver: true,
    }).start();
    return () => loop.stop();
  }, [visible, phase, pulse, actionReveal, timelineReveal]);

  if (!visible) return null;

  const close = () => {
    Vibration.vibrate(35);
    deactivate().finally(onClose);
  };

  return (
    <Modal visible={visible} transparent={false} animationType="fade" onRequestClose={close}>
      {phase === 'countdown' ? (
        <LinearGradient colors={['#8B0000', '#CC0000', '#FF1010']} style={[sosFlowStyles.full, { minHeight: height }]}>
          <TouchableOpacity style={sosFlowStyles.closeButton} onPress={close} activeOpacity={0.85}>
            <Ionicons name="close" size={24} color="#FFFFFF" />
          </TouchableOpacity>
          <Text style={sosFlowStyles.countLabel}>Sending SOS in</Text>
          <View style={sosFlowStyles.countRingWrap}>
            <Svg width={160} height={160} viewBox="0 0 160 160">
              <Circle cx="80" cy="80" r={ringRadius} fill="none" stroke="rgba(255,255,255,0.12)" strokeWidth="6" />
              <AnimatedCircle
                cx="80"
                cy="80"
                r={ringRadius}
                fill="none"
                stroke="#FFFFFF"
                strokeWidth="6"
                strokeLinecap="round"
                strokeDasharray={`${ringCircumference}`}
                strokeDashoffset={ringDashOffset as any}
                rotation="-90"
                originX="80"
                originY="80"
              />
            </Svg>
            <Animated.Text style={[sosFlowStyles.countNumber, { transform: [{ scale: countScale }] }]}>
              {count}
            </Animated.Text>
          </View>
          <Text style={sosFlowStyles.countTitle}>SOS will be sent automatically</Text>
          <Text style={sosFlowStyles.countCopy}>Your guardians and emergency contacts will be alerted</Text>
          <TouchableOpacity style={sosFlowStyles.cancelButton} onPress={close} activeOpacity={0.85}>
            <Text style={sosFlowStyles.cancelText}>Cancel</Text>
          </TouchableOpacity>
        </LinearGradient>
      ) : null}

      {phase === 'activating' ? (
        <LinearGradient colors={['#8B0000', '#CC0000']} style={[sosFlowStyles.full, { minHeight: height }]}>
          <Animated.View style={[sosFlowStyles.activatingIcon, { transform: [{ scale: pulse }] }]}>
            <Text style={sosFlowStyles.activatingEmoji}>SOS</Text>
          </Animated.View>
        </LinearGradient>
      ) : null}

      {phase === 'active' ? (
        <View style={sosFlowStyles.activeScreen}>
          <View style={sosFlowStyles.activeTop}>
            <View style={sosFlowStyles.activeStatus}>
              <Animated.View style={[sosFlowStyles.liveDot, { transform: [{ scale: pulse }] }]} />
              <Text style={sosFlowStyles.activeStatusText}>SOS ACTIVE</Text>
            </View>
            <TouchableOpacity style={sosFlowStyles.resolvePill} onPress={close} activeOpacity={0.85}>
              <Text style={sosFlowStyles.resolveText}>Resolve</Text>
            </TouchableOpacity>
          </View>

          <ScrollView contentContainerStyle={sosFlowStyles.activeContent} showsVerticalScrollIndicator={false}>
            <Animated.View style={[sosFlowStyles.activeSiren, { transform: [{ scale: pulse }] }]}>
              <Text style={sosFlowStyles.sirenEmoji}>SOS</Text>
            </Animated.View>
            <Text style={sosFlowStyles.activeTitle}>SOS Activated</Text>
            <Text style={sosFlowStyles.activeCopy}>Help is on the way. Stay calm and safe.</Text>

            <Text style={sosFlowStyles.sectionLabel}>ACTIONS TAKEN</Text>
            <View style={sosFlowStyles.actionCard}>
              {checklist.map(([icon, label, color], index) => (
                <Animated.View
                  key={label}
                  style={[
                    sosFlowStyles.actionRow,
                    {
                      opacity: actionReveal[index],
                      transform: [{
                        translateX: actionReveal[index].interpolate({
                          inputRange: [0, 1],
                          outputRange: [-16, 0],
                        }),
                      }],
                    },
                  ]}
                >
                  <View style={[sosFlowStyles.actionIcon, { backgroundColor: `${color}22` }]}>
                    <Ionicons name={icon} size={18} color={color} />
                  </View>
                  <Text style={sosFlowStyles.actionText}>{label}</Text>
                  <Ionicons name="checkmark-circle" size={22} color="#22C55E" />
                </Animated.View>
              ))}
            </View>

            <Text style={sosFlowStyles.sectionLabel}>EMERGENCY TIMELINE</Text>
            <Animated.View
              style={[
                sosFlowStyles.timelineCard,
                {
                  opacity: timelineReveal,
                  transform: [{
                    translateY: timelineReveal.interpolate({ inputRange: [0, 1], outputRange: [8, 0] }),
                  }],
                },
              ]}
            >
              {[
                ['Now', 'SOS Triggered by you'],
                ['Now', 'Parent & Co-Parent Notified'],
                ['Now', 'Live Location Shared'],
              ].map(([time, label]) => (
                <View key={`${time}-${label}`} style={sosFlowStyles.timelineRow}>
                  <Text style={sosFlowStyles.timelineTime}>{time}</Text>
                  <View style={sosFlowStyles.timelineDot} />
                  <Text style={sosFlowStyles.timelineText}>{label}</Text>
                </View>
              ))}
            </Animated.View>
          </ScrollView>

          <View style={sosFlowStyles.bottomActions}>
            <TouchableOpacity style={sosFlowStyles.callParentButton} activeOpacity={0.86}>
              <Ionicons name="call-outline" size={20} color="#FFFFFF" />
              <Text style={sosFlowStyles.callParentText}>Call Parent Now</Text>
            </TouchableOpacity>
            <TouchableOpacity onPress={close} activeOpacity={0.86}>
              <Text style={sosFlowStyles.markResolvedText}>Mark as Resolved</Text>
            </TouchableOpacity>
          </View>
        </View>
      ) : null}
    </Modal>
  );
}

function ReferenceHomeDashboard() {
  return (
    <SafeAreaView style={refHome.safe} edges={['top']}>
      <ScrollView style={refHome.scroll} contentContainerStyle={refHome.content} showsVerticalScrollIndicator={false}>
        <LinearGradient colors={['#071225', '#17375B']} style={refHome.hero}>
          <View style={refHome.headerRow}>
            <View style={refHome.logoMark}>
              <Ionicons name="shield-checkmark" size={30} color="#16C7C7" />
            </View>
            <View style={refHome.greetingBlock}>
              <Text style={refHome.eyebrow}>GOOD MORNING</Text>
              <Text style={refHome.name}>Rajesh Sharma</Text>
            </View>
            <View style={refHome.bellWrap}>
              <Ionicons name="notifications-outline" size={23} color="#FFFFFF" />
              <View style={refHome.badge}><Text style={refHome.badgeText}>2</Text></View>
            </View>
          </View>

          <View style={refHome.monitorPill}>
            <View style={refHome.greenDot} />
            <Text style={refHome.monitorText}>AI Safety Monitoring Active</Text>
            <Text style={refHome.memberText}>4 members</Text>
          </View>
        </LinearGradient>

        <View style={refHome.scoreCard}>
          <View style={refHome.scoreRing}>
            <Text style={refHome.scoreNum}>92</Text>
            <Text style={refHome.scoreLabel}>SCORE</Text>
          </View>
          <View style={refHome.scoreCopy}>
            <Text style={refHome.scoreEyebrow}>FAMILY SAFETY SCORE</Text>
            <Text style={refHome.scoreTitle}>Excellent</Text>
            <Text style={refHome.scoreDesc}>All members protected - AI active</Text>
            <View style={refHome.chipRow}>
              {['AI On', 'Routes OK', 'SOS Ready'].map((item) => (
                <Text key={item} style={refHome.chip}>{item}</Text>
              ))}
            </View>
          </View>
        </View>

        <View style={refHome.locationCard}>
          <View style={refHome.locationHead}>
            <View style={refHome.locationTitleRow}>
              <Ionicons name="location" size={17} color="#F0447A" style={refHome.pinIcon} />
              <Text style={refHome.locationTitle}>Live Location</Text>
            </View>
            <Text style={refHome.mapLink}>View Full Map {'>'}</Text>
          </View>
          <View style={refHome.map}>
            {Array.from({ length: 9 }).map((_, i) => <View key={`v-${i}`} style={[refHome.gridV, { left: `${i * 12.5}%` }]} />)}
            {Array.from({ length: 6 }).map((_, i) => <View key={`h-${i}`} style={[refHome.gridH, { top: `${i * 18}%` }]} />)}
            <View style={refHome.road} />
            <View style={[refHome.tree, { left: '8%', top: '23%' }]} />
            <View style={[refHome.treeSmall, { left: '16%', top: '31%' }]} />
            <View style={[refHome.tree, { right: '14%', top: '74%' }]} />
            <View style={[refHome.treeSmall, { right: '9%', top: '82%' }]} />
            <View style={refHome.school}><Text style={refHome.schoolText}>SCHOOL</Text></View>
            <View style={refHome.homeMarker}><Ionicons name="home" size={18} color="#FFFFFF" /></View>
            <View style={refHome.childMarker}>
              <Ionicons name="person" size={22} color="#192238" />
            </View>
          </View>
          <View style={refHome.memberCard}>
            <View style={refHome.memberAvatar}><Ionicons name="person" size={22} color="#192238" /></View>
            <View style={refHome.memberInfo}>
              <View style={refHome.memberNameRow}>
                <Text style={refHome.childName}>Priya</Text>
                <Text style={refHome.rolePill}>Son</Text>
              </View>
              <Text style={refHome.address}>DPS School, Sector...</Text>
            </View>
            <View style={refHome.memberMeta}>
              <Text style={refHome.justNow}>Just now</Text>
              <Text style={refHome.battery}>87%</Text>
            </View>
            <Text style={refHome.safePill}>Safe</Text>
          </View>
        </View>

        <View style={refHome.deepScoreCard}>
          <View style={refHome.deepScoreHead}>
            <View>
              <Text style={refHome.sectionEyebrow}>FAMILY SAFETY SCORE</Text>
              <View style={refHome.bigScoreRow}>
                <Text style={refHome.bigScore}>85</Text>
                <Text style={refHome.bigScoreTotal}>/100</Text>
              </View>
              <Text style={refHome.goodText}>Good</Text>
            </View>
            <View style={refHome.shieldBadge}>
              <Ionicons name="shield-outline" size={28} color="#F59E0B" />
            </View>
          </View>
          <View style={refHome.divider} />
          <View style={refHome.gaugeRow}>
            <MiniGauge value="92" label="Protection" status="Excellent" color="#39D879" icon="shield-outline" />
            <MiniGauge value="85" label="Permissions" status="Good" color="#F59E0B" icon="lock-closed-outline" />
            <MiniGauge value="78" label="Device" status="Good" color="#F59E0B" icon="phone-portrait-outline" />
          </View>
          <View style={refHome.healthTiles}>
            {['Overall health', 'Permissions granted', 'Device health'].map((item, index) => (
              <View key={item} style={refHome.healthTile}>
                <View style={[refHome.healthLine, { backgroundColor: index === 0 ? '#39D879' : '#F59E0B' }]} />
                <Text style={refHome.healthTileText}>{item}</Text>
              </View>
            ))}
          </View>
        </View>

        <View style={refHome.compromisedBanner}>
          <Ionicons name="warning-outline" size={15} color="#FF4B55" />
          <Text style={refHome.compromisedText}>Protection Compromised - Priya</Text>
        </View>

        <View style={refHome.smallChipWrap}>
          {['AI', 'Location', 'Mic', 'Wearable', '87%', 'Good'].map((item, index) => (
            <Text key={item} style={[refHome.tinyChip, index === 2 && refHome.tinyChipDanger]}>{item}</Text>
          ))}
        </View>

        <View style={refHome.whiteCard}>
          <View style={refHome.summaryHead}>
            <View>
              <Text style={refHome.sectionEyebrow}>SAFETY SUMMARY</Text>
              <Text style={refHome.summaryDate}>Today, Jun 12</Text>
            </View>
            <View style={refHome.segmentTabs}>
              <Text style={refHome.segmentActive}>Today</Text>
              <Text style={refHome.segmentInactive}>This Week</Text>
            </View>
          </View>
          <View style={refHome.metricGrid}>
            <MetricTile icon="checkmark-circle-outline" value="3" label="Check-ins" tone="#DBEAFE" />
            <MetricTile icon="warning-outline" value="2" label="Alerts Triggered" tone="#FEE2E2" />
            <MetricTile icon="git-branch-outline" value="2" label="Routes Completed" tone="#DCFCE7" />
            <MetricTile icon="battery-half-outline" value="74%" label="Avg Battery" tone="#FEF3C7" />
            <MetricTile icon="shield-checkmark-outline" value="14 h" label="Protected Hours" tone="#E2E8F0" />
            <MetricTile icon="star-outline" value="35" label="Safety Score" tone="#DBEAFE" danger />
          </View>
          <View style={refHome.reportRow}>
            <Text style={refHome.basedText}>Based on all family members</Text>
            <Text style={refHome.reportLink}>View Full Report {'->'}</Text>
          </View>
        </View>

        <View style={refHome.whiteCard}>
          <View style={refHome.healthHeader}>
            <View>
              <Text style={refHome.sectionEyebrow}>PROTECTION HEALTH</Text>
              <Text style={refHome.healthName}>Priya</Text>
            </View>
            <Text style={refHome.healthPercent}>85%</Text>
          </View>
          <View style={refHome.progressBar}><LinearGradient colors={['#0EA5E9', '#22C55E']} style={refHome.progressFill} /></View>
          <View style={refHome.healthStatusGrid}>
            <HealthStatus label="Location" status="Enabled" ok />
            <HealthStatus label="AI Monitoring" status="Enabled" ok />
            <HealthStatus label="Microphone" status="(by Member)" warning />
            <HealthStatus label="Wearable" status="Enabled" ok />
            <HealthStatus label="Background" status="Enabled" ok />
            <HealthStatus label="Notifications" status="Enabled" ok />
          </View>
          <View style={refHome.partialBanner}>
            <Ionicons name="warning-outline" size={18} color="#F59E0B" />
            <Text style={refHome.partialText}>Protection partially compromised</Text>
          </View>
        </View>

        <View style={refHome.whiteCard}>
          <View style={refHome.cardTitleRow}>
            <View>
              <Text style={refHome.sectionEyebrow}>FAMILY HIERARCHY</Text>
              <Text style={refHome.healthName}>Guardian Structure</Text>
            </View>
            <View style={refHome.crownPill}><Ionicons name="diamond-outline" size={20} color="#0B84FF" /></View>
          </View>
          <GuardianNode initial="R" name="Rajesh Sharma" role="Primary Parent" sub="Full Control" online />
          <View style={refHome.connector} />
          <GuardianNode initial="P" name="Priya Sharma" role="Co-Parent" sub="Monitoring Access" online />
          <View style={refHome.protectedLabel}><Text style={refHome.sectionEyebrow}>PROTECTED MEMBERS</Text></View>
          <View style={refHome.protectedRow}>
            <ProtectedMember initial="A" name="Aarav" role="Child" status="Safe" />
            <ProtectedMember initial="R" name="Riya" role="Woman" status="Safe" />
            <ProtectedMember initial="N" name="Nana" role="Senior" status="Attention" warning />
          </View>
          <View style={refHome.nanaNotice}>
            <Ionicons name="alert-circle-outline" size={16} color="#F59E0B" />
            <Text style={refHome.nanaNoticeText}>Nana needs attention</Text>
          </View>
        </View>

        <TouchableOpacity style={refHome.batteryAlert} activeOpacity={0.84}>
          <View style={refHome.batteryAlertIcon}><Ionicons name="warning-outline" size={28} color="#F59E0B" /></View>
          <View style={{ flex: 1 }}>
            <Text style={refHome.batteryAlertTitle}>Nana's battery is below 35%</Text>
            <Text style={refHome.batteryAlertSub}>Tap to view and respond</Text>
          </View>
          <Ionicons name="chevron-forward" size={22} color="#F59E0B" />
        </TouchableOpacity>

        <DashboardSectionTitle title="QUICK ACTIONS" />
        <View style={refHome.quickRow}>
          <ActionTile icon="call-outline" label="Call" color="#22C55E" />
          <ActionTile icon="location-outline" label="Track" color="#0EA5E9" />
          <ActionTile icon="shield-outline" label="SOS" color="#EF4444" />
          <ActionTile icon="add" label="Add" color="#8B5CF6" />
        </View>

        <View style={refHome.familySectionHead}>
          <Text style={refHome.sectionEyebrow}>FAMILY CIRCLE</Text>
          <Text style={refHome.manageLink}>Manage {'->'}</Text>
        </View>
        <View style={refHome.familyParentCard}>
          <View style={refHome.parentAvatar}><Ionicons name="person" size={24} color="#0F172A" /></View>
          <View style={{ flex: 1 }}>
            <Text style={refHome.familyName}>Rajesh Sharma</Text>
            <Text style={refHome.familySub}>Father  -  Co-Guardian</Text>
          </View>
          <Text style={refHome.onlineText}>Online</Text>
        </View>
        <View style={refHome.familyChildCard}>
          <View style={refHome.memberAvatar}><Ionicons name="person" size={23} color="#192238" /></View>
          <View style={{ flex: 1 }}>
            <View style={refHome.memberNameRow}>
              <Text style={refHome.childName}>Aarav</Text>
              <Text style={refHome.rolePill}>Son</Text>
              <Text style={refHome.safeMini}>Safe</Text>
            </View>
            <Text style={refHome.address}>DPS School  2m ago</Text>
          </View>
          <Text style={refHome.battery}>87%</Text>
          <View style={refHome.memberActions}>
            <Text style={refHome.callAction}>Call</Text>
            <Text style={refHome.trackAction}>Track</Text>
            <Text style={refHome.sosAction}>SOS</Text>
          </View>
        </View>

        <DashboardSectionTitle title="TODAY'S ACTIVITY" />
        <View style={refHome.activityCard}>
          <ActivityRow icon="checkbox" title="Priya arrived home safely" time="03:05 PM" color="#22C55E" />
          <ActivityRow icon="school-outline" title="Priya left school" time="02:35 PM" color="#F59E0B" />
          <ActivityRow icon="battery-half-outline" title="Priya's battery 87% - Good" time="01:44 PM" color="#22C55E" />
          <ActivityRow icon="checkbox" title="Priya arrived at school" time="08:42 AM" color="#22C55E" />
          <ActivityRow icon="walk-outline" title="Safe Walk started: Home -> School" time="08:38 AM" color="#0EA5E9" />
          <ActivityRow icon="sunny-outline" title="Morning check-in completed" time="08:15 AM" color="#F59E0B" />
        </View>

        <DashboardSectionTitle title="MONITORING STATUS" />
        <View style={refHome.monitorGrid}>
          <MonitorTile icon="pulse-outline" title="AI Monitoring" status="Active" color="#0EA5E9" />
          <MonitorTile icon="location-outline" title="Route Monitoring" status="Active" color="#22C55E" />
          <MonitorTile icon="flash-outline" title="SOS System" status="Active" color="#EF4444" />
          <MonitorTile icon="wifi-outline" title="Wearables" status="Off" color="#94A3B8" />
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

function MiniGauge({ value, label, status, color, icon }: any) {
  return (
    <View style={refHome.miniGauge}>
      <View style={[refHome.miniRing, { borderColor: color }]}>
        <Ionicons name={icon} size={17} color={color} />
        <Text style={refHome.miniValue}>{value}</Text>
      </View>
      <Text style={refHome.miniLabel}>{label}</Text>
      <Text style={[refHome.miniStatus, { color }]}>{status}</Text>
    </View>
  );
}

function MetricTile({ icon, value, label, tone, danger }: any) {
  return (
    <View style={refHome.metricTile}>
      <View style={[refHome.metricIcon, { backgroundColor: tone }]}>
        <Ionicons name={icon} size={18} color={danger ? '#EF4444' : '#0EA5E9'} />
      </View>
      <Text style={refHome.metricValue}>{value}</Text>
      <Text style={refHome.metricLabel}>{label}</Text>
    </View>
  );
}

function HealthStatus({ label, status, ok, warning }: any) {
  return (
    <View style={refHome.healthStatusItem}>
      <Ionicons name={warning ? 'warning-outline' : ok ? 'checkmark-circle-outline' : 'ellipse-outline'} size={18} color={warning ? '#F59E0B' : '#22C55E'} />
      <Text style={refHome.healthStatusLabel}>{label} <Text style={[refHome.healthStatusSmall, warning && refHome.healthStatusWarn]}>{status}</Text></Text>
    </View>
  );
}

function GuardianNode({ initial, name, role, sub, online }: any) {
  return (
    <View style={refHome.guardianNode}>
      <View style={refHome.nodeAvatar}><Text style={refHome.nodeInitial}>{initial}</Text><View style={refHome.nodeOnline} /></View>
      <View style={{ flex: 1 }}>
        <Text style={refHome.nodeName}>{name}</Text>
        <Text style={refHome.nodeRole}>{role}</Text>
        <Text style={refHome.nodeSub}>{sub}</Text>
      </View>
      <Text style={refHome.onlineText}>{online ? 'Online' : 'Offline'}</Text>
    </View>
  );
}

function ProtectedMember({ initial, name, role, status, warning }: any) {
  return (
    <View style={refHome.protectedMini}>
      <View style={refHome.protectedAvatar}><Text style={refHome.nodeInitial}>{initial}</Text><View style={[refHome.nodeOnline, warning && refHome.nodeWarn]} /></View>
      <Text style={refHome.protectedName}>{name}</Text>
      <Text style={refHome.protectedRole}>{role}</Text>
      <Text style={[refHome.protectedStatus, warning && refHome.protectedWarn]}>{status}</Text>
    </View>
  );
}

function DashboardSectionTitle({ title }: { title: string }) {
  return <Text style={refHome.sectionHeader}>{title}</Text>;
}

function ActionTile({ icon, label, color }: any) {
  return (
    <TouchableOpacity style={refHome.actionTile} activeOpacity={0.84}>
      <View style={[refHome.actionIcon, { backgroundColor: `${color}18` }]}>
        <Ionicons name={icon} size={27} color={color} />
      </View>
      <Text style={refHome.actionLabel}>{label}</Text>
    </TouchableOpacity>
  );
}

function ActivityRow({ icon, title, time, color }: any) {
  return (
    <View style={refHome.activityRow}>
      <View style={[refHome.activityIcon, { backgroundColor: `${color}16` }]}>
        <Ionicons name={icon} size={23} color={color} />
      </View>
      <View style={{ flex: 1 }}>
        <Text style={refHome.activityTitle}>{title}</Text>
        <Text style={refHome.activityTime}>{time}</Text>
      </View>
    </View>
  );
}

function MonitorTile({ icon, title, status, color }: any) {
  return (
    <View style={refHome.monitorTile}>
      <View style={[refHome.monitorStatusIcon, { backgroundColor: `${color}16` }]}>
        <Ionicons name={icon} size={22} color={color} />
      </View>
      <View>
        <Text style={refHome.monitorTileTitle}>{title}</Text>
        <Text style={[refHome.monitorTileStatus, { color: status === 'Off' ? '#94A3B8' : '#22C55E' }]}>{status}</Text>
      </View>
    </View>
  );
}

const refHome = StyleSheet.create({
  safe: { flex: 1, backgroundColor: '#F5F7FB' },
  scroll: { flex: 1 },
  content: { paddingBottom: 18 },
  hero: { paddingHorizontal: 26, paddingTop: 34, paddingBottom: 22 },
  headerRow: { flexDirection: 'row', alignItems: 'center' },
  logoMark: { width: 40, height: 40, borderRadius: 14, alignItems: 'center', justifyContent: 'center' },
  greetingBlock: { flex: 1, marginLeft: 10 },
  eyebrow: { color: '#9FB5D1', fontSize: 12, letterSpacing: 2, fontWeight: '800' },
  name: { color: '#FFFFFF', fontSize: 20, lineHeight: 26, fontWeight: '900', marginTop: 2 },
  bellWrap: { width: 48, height: 48, borderRadius: 24, alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(255,255,255,0.12)' },
  badge: { position: 'absolute', top: -2, right: -1, width: 21, height: 21, borderRadius: 11, alignItems: 'center', justifyContent: 'center', backgroundColor: '#FF4B55' },
  badgeText: { color: '#FFFFFF', fontSize: 12, fontWeight: '900' },
  monitorPill: { marginTop: 22, height: 42, borderRadius: 21, borderWidth: 1, borderColor: 'rgba(56,189,248,0.35)', backgroundColor: 'rgba(14, 116, 182, 0.48)', flexDirection: 'row', alignItems: 'center', paddingHorizontal: 14 },
  greenDot: { width: 14, height: 14, borderRadius: 7, backgroundColor: '#35D07F', marginRight: 10 },
  monitorText: { flex: 1, color: '#FFFFFF', fontSize: 15, fontWeight: '900' },
  memberText: { color: '#9FB5D1', fontSize: 13, fontWeight: '700' },
  scoreCard: { marginHorizontal: 26, marginTop: 20, minHeight: 165, borderRadius: 18, backgroundColor: '#FFFFFF', flexDirection: 'row', alignItems: 'center', padding: 22, shadowColor: '#0F172A', shadowOpacity: 0.08, shadowOffset: { width: 0, height: 10 }, shadowRadius: 24, elevation: 4 },
  scoreRing: { width: 112, height: 112, borderRadius: 56, borderWidth: 9, borderColor: '#19A7EE', alignItems: 'center', justifyContent: 'center', marginRight: 22 },
  scoreNum: { color: '#07111F', fontSize: 29, fontWeight: '900' },
  scoreLabel: { color: '#395D8A', fontSize: 11, fontWeight: '800' },
  scoreCopy: { flex: 1 },
  scoreEyebrow: { color: '#5F789D', fontSize: 14, fontWeight: '900', letterSpacing: 2 },
  scoreTitle: { color: '#07111F', fontSize: 23, fontWeight: '900', marginTop: 10 },
  scoreDesc: { color: '#56657A', fontSize: 15, marginTop: 6 },
  chipRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 9, marginTop: 12 },
  chip: { color: '#148048', fontSize: 12, fontWeight: '900', paddingHorizontal: 10, paddingVertical: 5, borderRadius: 12, backgroundColor: '#DDFBE8' },
  locationCard: { marginHorizontal: 26, marginTop: 20, borderRadius: 18, backgroundColor: '#FFFFFF', overflow: 'hidden', shadowColor: '#0F172A', shadowOpacity: 0.08, shadowOffset: { width: 0, height: 10 }, shadowRadius: 24, elevation: 4 },
  locationHead: { height: 52, paddingHorizontal: 20, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  locationTitleRow: { flexDirection: 'row', alignItems: 'center' },
  pinIcon: { marginRight: 7 },
  locationTitle: { color: '#07111F', fontSize: 17, fontWeight: '900' },
  mapLink: { color: '#0B84FF', fontSize: 14, fontWeight: '900' },
  map: { height: 228, backgroundColor: '#EAF4FF', overflow: 'hidden' },
  gridV: { position: 'absolute', top: 0, bottom: 0, width: 1, backgroundColor: '#D3E6FA' },
  gridH: { position: 'absolute', left: 0, right: 0, height: 1, backgroundColor: '#D3E6FA' },
  road: { position: 'absolute', left: -5, right: 30, top: 144, height: 18, borderRadius: 9, backgroundColor: '#A6D0FF', transform: [{ rotate: '-18deg' }] },
  tree: { position: 'absolute', width: 30, height: 22, borderRadius: 14, backgroundColor: '#8BE2B6' },
  treeSmall: { position: 'absolute', width: 22, height: 18, borderRadius: 10, backgroundColor: '#77D9A6' },
  school: { position: 'absolute', right: 56, top: 38, width: 58, height: 42, borderRadius: 6, alignItems: 'center', justifyContent: 'center', backgroundColor: '#BBD9FF' },
  schoolText: { position: 'absolute', top: -15, color: '#3779DD', fontSize: 9, fontWeight: '900' },
  homeMarker: { position: 'absolute', left: 24, bottom: 26, width: 24, height: 24, borderRadius: 12, alignItems: 'center', justifyContent: 'center', backgroundColor: '#2CCB74', borderWidth: 3, borderColor: '#FF5757' },
  childMarker: { position: 'absolute', left: '46%', top: '50%', width: 48, height: 48, borderRadius: 24, alignItems: 'center', justifyContent: 'center', backgroundColor: '#FFFFFF', borderWidth: 4, borderColor: '#8B5CF6' },
  avatar: { fontSize: 20 },
  memberCard: { minHeight: 78, paddingHorizontal: 20, flexDirection: 'row', alignItems: 'center' },
  memberAvatar: { width: 45, height: 45, borderRadius: 23, borderWidth: 3, borderColor: '#8B5CF6', alignItems: 'center', justifyContent: 'center', marginRight: 12 },
  memberInfo: { flex: 1 },
  memberNameRow: { flexDirection: 'row', alignItems: 'center' },
  childName: { color: '#07111F', fontSize: 17, fontWeight: '900' },
  rolePill: { marginLeft: 8, color: '#8B5CF6', fontSize: 12, fontWeight: '900', paddingHorizontal: 7, paddingVertical: 4, borderRadius: 10, backgroundColor: '#EFE7FF' },
  address: { color: '#516279', fontSize: 13, marginTop: 6 },
  memberMeta: { alignItems: 'flex-end', marginRight: 8 },
  justNow: { color: '#8A98AE', fontSize: 11, fontWeight: '700' },
  battery: { color: '#07111F', fontSize: 12, fontWeight: '900', marginTop: 7 },
  safePill: { color: '#047A3C', fontSize: 13, fontWeight: '900', paddingHorizontal: 13, paddingVertical: 8, borderRadius: 14, backgroundColor: '#DDFBE8' },
  deepScoreCard: { marginHorizontal: 26, marginTop: 20, borderRadius: 18, backgroundColor: '#FFFFFF', padding: 22, shadowColor: '#0F172A', shadowOpacity: 0.08, shadowOffset: { width: 0, height: 10 }, shadowRadius: 24, elevation: 4 },
  deepScoreHead: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start' },
  sectionEyebrow: { color: '#60799D', fontSize: 14, fontWeight: '900', letterSpacing: 2 },
  bigScoreRow: { flexDirection: 'row', alignItems: 'flex-end', marginTop: 6 },
  bigScore: { color: '#F59E0B', fontSize: 42, lineHeight: 48, fontWeight: '900' },
  bigScoreTotal: { color: '#607084', fontSize: 18, fontWeight: '700', marginBottom: 7 },
  goodText: { color: '#F59E0B', fontSize: 14, fontWeight: '800', marginTop: 2 },
  shieldBadge: { width: 58, height: 58, borderRadius: 29, alignItems: 'center', justifyContent: 'center', backgroundColor: '#FFF4DC' },
  divider: { height: 1, backgroundColor: '#E6EDF5', marginTop: 20, marginBottom: 20 },
  gaugeRow: { flexDirection: 'row', justifyContent: 'space-between' },
  miniGauge: { alignItems: 'center', width: '31%' },
  miniRing: { width: 84, height: 84, borderRadius: 42, borderWidth: 8, alignItems: 'center', justifyContent: 'center', borderRightColor: '#E6EDF5' },
  miniValue: { color: '#07111F', fontSize: 21, fontWeight: '900', marginTop: 2 },
  miniLabel: { color: '#07111F', fontSize: 14, fontWeight: '800', marginTop: 10 },
  miniStatus: { fontSize: 12, fontWeight: '700', marginTop: 4 },
  healthTiles: { flexDirection: 'row', gap: 8, marginTop: 20 },
  healthTile: { flex: 1, minHeight: 60, borderRadius: 12, alignItems: 'center', justifyContent: 'center', backgroundColor: '#F3F7FC', paddingHorizontal: 6 },
  healthLine: { position: 'absolute', top: 10, left: 14, right: 14, height: 4, borderRadius: 2 },
  healthTileText: { color: '#607084', fontSize: 11, textAlign: 'center', fontWeight: '700', marginTop: 12 },
  compromisedBanner: { marginHorizontal: 26, marginTop: 20, minHeight: 38, borderRadius: 15, borderWidth: 1, borderColor: '#FFB9BE', backgroundColor: '#FFF1F2', flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: 16 },
  compromisedText: { color: '#FF4B55', fontSize: 14, fontWeight: '900' },
  smallChipWrap: { marginHorizontal: 26, marginTop: 8, flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  tinyChip: { overflow: 'hidden', color: '#13894F', fontSize: 12, fontWeight: '900', paddingHorizontal: 10, paddingVertical: 5, borderRadius: 12, backgroundColor: '#DDFBE8' },
  tinyChipDanger: { color: '#D94848', backgroundColor: '#FEE2E2' },
  whiteCard: { marginHorizontal: 26, marginTop: 20, borderRadius: 18, backgroundColor: '#FFFFFF', padding: 22, shadowColor: '#0F172A', shadowOpacity: 0.08, shadowOffset: { width: 0, height: 10 }, shadowRadius: 24, elevation: 4 },
  summaryHead: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 },
  summaryDate: { color: '#07111F', fontSize: 17, fontWeight: '900', marginTop: 8 },
  segmentTabs: { flexDirection: 'row', backgroundColor: '#F1F5F9', borderRadius: 17, padding: 3 },
  segmentActive: { color: '#0F172A', fontSize: 13, fontWeight: '900', paddingHorizontal: 18, paddingVertical: 8, borderRadius: 14, backgroundColor: '#FFFFFF' },
  segmentInactive: { color: '#607084', fontSize: 13, fontWeight: '900', paddingHorizontal: 14, paddingVertical: 8 },
  metricGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 12, marginTop: 20 },
  metricTile: { width: '30.8%', minHeight: 126, borderRadius: 15, backgroundColor: '#F5F8FC', padding: 14, justifyContent: 'center' },
  metricIcon: { width: 36, height: 36, borderRadius: 18, alignItems: 'center', justifyContent: 'center', marginBottom: 14 },
  metricValue: { color: '#07111F', fontSize: 26, fontWeight: '900' },
  metricLabel: { color: '#52647C', fontSize: 12, lineHeight: 17, fontWeight: '700', marginTop: 3 },
  reportRow: { borderTopWidth: 1, borderTopColor: '#E6EDF5', marginTop: 20, paddingTop: 14, flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: 10 },
  basedText: { color: '#52647C', fontSize: 12, fontWeight: '700' },
  reportLink: { color: '#0B84FF', fontSize: 13, fontWeight: '900' },
  healthHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start' },
  healthName: { color: '#07111F', fontSize: 18, fontWeight: '900', marginTop: 6 },
  healthPercent: { color: '#F59E0B', fontSize: 38, fontWeight: '900' },
  progressBar: { height: 12, borderRadius: 6, backgroundColor: '#E8EEF6', overflow: 'hidden', marginTop: 18 },
  progressFill: { width: '85%', height: 12, borderRadius: 6 },
  healthStatusGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 16, marginTop: 22 },
  healthStatusItem: { width: '46%', flexDirection: 'row', alignItems: 'flex-start', gap: 9, minHeight: 34 },
  healthStatusLabel: { flex: 1, color: '#07111F', fontSize: 14, fontWeight: '900' },
  healthStatusSmall: { color: '#22C55E', fontSize: 12, fontWeight: '700' },
  healthStatusWarn: { color: '#F59E0B' },
  partialBanner: { minHeight: 50, borderRadius: 16, borderWidth: 1, borderColor: '#FAD898', backgroundColor: '#FFF8EB', flexDirection: 'row', alignItems: 'center', gap: 10, paddingHorizontal: 14, marginTop: 16 },
  partialText: { color: '#AA4E00', fontSize: 14, fontWeight: '900' },
  cardTitleRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  crownPill: { width: 38, height: 38, borderRadius: 19, alignItems: 'center', justifyContent: 'center', backgroundColor: '#EAF4FF' },
  guardianNode: { minHeight: 100, borderRadius: 18, borderWidth: 1, borderColor: '#DCE5F0', backgroundColor: '#F7FAFE', flexDirection: 'row', alignItems: 'center', gap: 14, padding: 16, marginTop: 18 },
  nodeAvatar: { width: 66, height: 66, borderRadius: 33, alignItems: 'center', justifyContent: 'center', backgroundColor: '#0B8FF0', shadowColor: '#0B8FF0', shadowOpacity: 0.25, shadowOffset: { width: 0, height: 8 }, shadowRadius: 15, elevation: 4 },
  nodeInitial: { color: '#FFFFFF', fontSize: 25, fontWeight: '900' },
  nodeOnline: { position: 'absolute', right: 0, bottom: 5, width: 14, height: 14, borderRadius: 7, borderWidth: 2, borderColor: '#FFFFFF', backgroundColor: '#22C55E' },
  nodeWarn: { backgroundColor: '#F59E0B' },
  nodeName: { color: '#07111F', fontSize: 17, fontWeight: '900' },
  nodeRole: { alignSelf: 'flex-start', overflow: 'hidden', color: '#FFFFFF', fontSize: 12, fontWeight: '900', paddingHorizontal: 10, paddingVertical: 5, borderRadius: 12, backgroundColor: '#0B8FF0', marginTop: 6 },
  nodeSub: { color: '#607084', fontSize: 12, fontWeight: '700', marginTop: 6 },
  onlineText: { color: '#22C55E', fontSize: 12, fontWeight: '900' },
  connector: { alignSelf: 'center', width: 1, height: 28, backgroundColor: '#DCE5F0' },
  protectedLabel: { marginTop: 20, marginBottom: 14 },
  protectedRow: { flexDirection: 'row', gap: 10 },
  protectedMini: { flex: 1, minHeight: 156, borderRadius: 16, borderWidth: 1, borderColor: '#DCE5F0', backgroundColor: '#F7FAFE', alignItems: 'center', justifyContent: 'center', padding: 10 },
  protectedAvatar: { width: 52, height: 52, borderRadius: 26, alignItems: 'center', justifyContent: 'center', backgroundColor: '#0B8FF0', marginBottom: 10 },
  protectedName: { color: '#07111F', fontSize: 14, fontWeight: '900' },
  protectedRole: { color: '#607084', fontSize: 12, fontWeight: '700', marginTop: 3 },
  protectedStatus: { overflow: 'hidden', color: '#22C55E', fontSize: 11, fontWeight: '900', paddingHorizontal: 8, paddingVertical: 5, borderRadius: 10, backgroundColor: '#DDFBE8', marginTop: 8 },
  protectedWarn: { color: '#F59E0B', backgroundColor: '#FEF3C7' },
  nanaNotice: { minHeight: 46, borderRadius: 14, borderWidth: 1, borderColor: '#FAD898', backgroundColor: '#FFF8EB', flexDirection: 'row', alignItems: 'center', gap: 10, paddingHorizontal: 16, marginTop: 16 },
  nanaNoticeText: { color: '#AA4E00', fontSize: 14, fontWeight: '900' },
  batteryAlert: { marginHorizontal: 26, marginTop: 20, minHeight: 84, borderRadius: 18, borderWidth: 1, borderColor: '#FAD898', backgroundColor: '#FFF8EB', flexDirection: 'row', alignItems: 'center', gap: 14, padding: 16 },
  batteryAlertIcon: { width: 54, height: 54, borderRadius: 27, alignItems: 'center', justifyContent: 'center', backgroundColor: '#FEF3C7' },
  batteryAlertTitle: { color: '#8A3E00', fontSize: 16, fontWeight: '900' },
  batteryAlertSub: { color: '#B45309', fontSize: 14, fontWeight: '800', marginTop: 5 },
  sectionHeader: { marginHorizontal: 26, marginTop: 22, marginBottom: 12, color: '#60799D', fontSize: 15, fontWeight: '900', letterSpacing: 2 },
  quickRow: { flexDirection: 'row', gap: 11, marginHorizontal: 26 },
  actionTile: { flex: 1, minHeight: 106, borderRadius: 16, backgroundColor: '#FFFFFF', alignItems: 'center', justifyContent: 'center', shadowColor: '#0F172A', shadowOpacity: 0.06, shadowOffset: { width: 0, height: 8 }, shadowRadius: 18, elevation: 2 },
  actionIcon: { width: 52, height: 52, borderRadius: 26, alignItems: 'center', justifyContent: 'center', marginBottom: 10 },
  actionLabel: { color: '#07111F', fontSize: 12, fontWeight: '900' },
  familySectionHead: { marginHorizontal: 26, marginTop: 22, marginBottom: 12, flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  manageLink: { color: '#0B84FF', fontSize: 15, fontWeight: '900' },
  familyParentCard: { marginHorizontal: 26, minHeight: 76, borderRadius: 16, backgroundColor: '#FFFFFF', flexDirection: 'row', alignItems: 'center', gap: 12, padding: 14, shadowColor: '#0F172A', shadowOpacity: 0.06, shadowOffset: { width: 0, height: 8 }, shadowRadius: 18, elevation: 2 },
  parentAvatar: { width: 54, height: 54, borderRadius: 27, borderWidth: 3, borderColor: '#55DD8B', alignItems: 'center', justifyContent: 'center', backgroundColor: '#F0FDF4' },
  familyName: { color: '#07111F', fontSize: 17, fontWeight: '900' },
  familySub: { color: '#94A3B8', fontSize: 12, fontWeight: '800', marginTop: 5 },
  familyChildCard: { marginHorizontal: 26, marginTop: 12, borderRadius: 16, backgroundColor: '#FFFFFF', flexDirection: 'row', alignItems: 'center', gap: 12, padding: 14, flexWrap: 'wrap', borderWidth: 1, borderColor: '#EFE7FF' },
  safeMini: { marginLeft: 8, color: '#16A34A', fontSize: 11, fontWeight: '900', paddingHorizontal: 8, paddingVertical: 4, borderRadius: 10, backgroundColor: '#DCFCE7' },
  memberActions: { width: '100%', flexDirection: 'row', gap: 10, marginTop: 8 },
  callAction: { flex: 1, textAlign: 'center', overflow: 'hidden', borderRadius: 16, backgroundColor: '#22C55E', color: '#FFFFFF', fontSize: 15, fontWeight: '900', paddingVertical: 13 },
  trackAction: { flex: 1, textAlign: 'center', overflow: 'hidden', borderRadius: 16, backgroundColor: '#0B84FF', color: '#FFFFFF', fontSize: 15, fontWeight: '900', paddingVertical: 13 },
  sosAction: { flex: 1, textAlign: 'center', overflow: 'hidden', borderRadius: 16, backgroundColor: '#EF4444', color: '#FFFFFF', fontSize: 15, fontWeight: '900', paddingVertical: 13 },
  activityCard: { marginHorizontal: 26, borderRadius: 18, backgroundColor: '#FFFFFF', overflow: 'hidden', shadowColor: '#0F172A', shadowOpacity: 0.08, shadowOffset: { width: 0, height: 10 }, shadowRadius: 24, elevation: 4 },
  activityRow: { minHeight: 78, flexDirection: 'row', alignItems: 'center', gap: 14, paddingHorizontal: 20, borderBottomWidth: 1, borderBottomColor: '#EEF2F7' },
  activityIcon: { width: 38, height: 38, borderRadius: 19, alignItems: 'center', justifyContent: 'center' },
  activityTitle: { color: '#07111F', fontSize: 16, fontWeight: '800' },
  activityTime: { color: '#8A98AE', fontSize: 14, fontWeight: '700', marginTop: 4 },
  monitorGrid: { marginHorizontal: 26, flexDirection: 'row', flexWrap: 'wrap', gap: 12, paddingBottom: 78 },
  monitorTile: { width: '48%', minHeight: 82, borderRadius: 16, backgroundColor: '#FFFFFF', flexDirection: 'row', alignItems: 'center', gap: 12, padding: 15, shadowColor: '#0F172A', shadowOpacity: 0.06, shadowOffset: { width: 0, height: 8 }, shadowRadius: 18, elevation: 2 },
  monitorStatusIcon: { width: 42, height: 42, borderRadius: 21, alignItems: 'center', justifyContent: 'center' },
  monitorTileTitle: { color: '#07111F', fontSize: 13, fontWeight: '900' },
  monitorTileStatus: { fontSize: 12, fontWeight: '800', marginTop: 4 },
});

const protectedHome = StyleSheet.create({
  safe: { flex: 1, backgroundColor: '#F5F7FB' },
  scroll: { flex: 1 },
  content: { paddingBottom: 18 },
  topStatus: { height: 30, alignItems: 'center', justifyContent: 'center', backgroundColor: '#12A664' },
  statusText: { color: '#FFFFFF', fontSize: 12, fontWeight: '900' },
  profileHead: { minHeight: 76, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 20, backgroundColor: '#FFFFFF' },
  personName: { color: '#0F172A', fontSize: 19, fontWeight: '900' },
  personRole: { color: '#667085', fontSize: 12, fontWeight: '800', marginTop: 4 },
  roleBadge: { color: '#9A6B00', fontSize: 12, fontWeight: '900', paddingHorizontal: 10, paddingVertical: 6, borderRadius: 12, backgroundColor: '#FEF3C7' },
  guardianRow: { flexDirection: 'row', gap: 12, paddingHorizontal: 20, paddingTop: 16 },
  guardianCard: { flex: 1, borderRadius: 16, backgroundColor: '#FFFFFF', alignItems: 'center', padding: 12, shadowColor: '#0F172A', shadowOpacity: 0.05, shadowOffset: { width: 0, height: 7 }, shadowRadius: 16, elevation: 2 },
  avatarCircle: { width: 48, height: 48, borderRadius: 24, alignItems: 'center', justifyContent: 'center', backgroundColor: '#EAF2FF' },
  guardianName: { color: '#0F172A', fontSize: 15, fontWeight: '900', marginTop: 8 },
  guardianRole: { color: '#8A96A8', fontSize: 11, fontWeight: '700', marginTop: 2 },
  callGreen: { height: 34, alignSelf: 'stretch', borderRadius: 10, marginTop: 10, backgroundColor: '#22C55E', flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6 },
  callBlue: { height: 34, alignSelf: 'stretch', borderRadius: 10, marginTop: 10, backgroundColor: '#0EA5E9', flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6 },
  callText: { color: '#FFFFFF', fontSize: 13, fontWeight: '900' },
  safeWalkBtn: { minHeight: 55, borderRadius: 14, marginHorizontal: 20, marginTop: 14, backgroundColor: '#8226D9', flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 10 },
  safeWalkText: { color: '#FFFFFF', fontSize: 15, fontWeight: '900', textAlign: 'center' },
  safeWalkSub: { color: 'rgba(255,255,255,0.75)', fontSize: 11, fontWeight: '700', textAlign: 'center' },
  sosCard: { minHeight: 236, borderRadius: 18, marginHorizontal: 20, marginTop: 14, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 20, backgroundColor: '#DE1736' },
  sosTitle: { color: '#FFFFFF', fontSize: 34, letterSpacing: 4, fontWeight: '900', marginTop: 9 },
  sosSub: { color: '#FFFFFF', fontSize: 13, fontWeight: '900', marginTop: 10 },
  sosLine: { color: 'rgba(255,255,255,0.90)', fontSize: 12, fontWeight: '700', marginTop: 8 },
  actionPair: { flexDirection: 'row', gap: 12, paddingHorizontal: 20, marginTop: 14 },
  safeButton: { flex: 1, height: 48, borderRadius: 12, alignItems: 'center', justifyContent: 'center', backgroundColor: '#22C55E' },
  etaButton: { flex: 1, height: 48, borderRadius: 12, alignItems: 'center', justifyContent: 'center', backgroundColor: '#7C3AED' },
  safeButtonText: { color: '#FFFFFF', fontSize: 15, fontWeight: '900' },
  sectionCard: { marginHorizontal: 20, marginTop: 18, borderRadius: 18, backgroundColor: '#FFFFFF', padding: 16, shadowColor: '#0F172A', shadowOpacity: 0.05, shadowOffset: { width: 0, height: 7 }, shadowRadius: 16, elevation: 2 },
  sectionTitle: { color: '#0F172A', fontSize: 18, fontWeight: '900' },
  sectionSub: { color: '#667085', fontSize: 12, fontWeight: '700', marginTop: 4 },
  segmentRow: { flexDirection: 'row', gap: 8, marginTop: 14 },
  segmentOn: { flex: 1, textAlign: 'center', overflow: 'hidden', borderRadius: 14, backgroundColor: '#0EA5E9', color: '#FFFFFF', fontSize: 12, fontWeight: '900', paddingVertical: 8 },
  segmentOff: { flex: 1, textAlign: 'center', overflow: 'hidden', borderRadius: 14, backgroundColor: '#F1F5F9', color: '#667085', fontSize: 12, fontWeight: '900', paddingVertical: 8 },
  toggleRow: { minHeight: 44, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', borderTopWidth: 1, borderTopColor: '#EEF2F7', marginTop: 10, paddingTop: 10 },
  toggleText: { color: '#0F172A', fontSize: 14, fontWeight: '800' },
  toggleOn: { width: 42, height: 24, borderRadius: 12, backgroundColor: '#22C55E', alignItems: 'flex-end', justifyContent: 'center', paddingHorizontal: 3 },
  toggleKnob: { width: 18, height: 18, borderRadius: 9, backgroundColor: '#FFFFFF' },
  routeCard: { marginHorizontal: 20, marginTop: 18, borderRadius: 18, backgroundColor: '#FFFFFF', padding: 16, shadowColor: '#0F172A', shadowOpacity: 0.05, shadowOffset: { width: 0, height: 7 }, shadowRadius: 16, elevation: 2 },
  routeItem: { minHeight: 70, borderRadius: 14, backgroundColor: '#F8FAFC', flexDirection: 'row', alignItems: 'center', gap: 10, paddingHorizontal: 12, marginTop: 12 },
  routeTitle: { color: '#0F172A', fontSize: 14, fontWeight: '900' },
  routeMeta: { color: '#667085', fontSize: 12, fontWeight: '700', marginTop: 4 },
  arrived: { color: '#10A15A', fontSize: 12, fontWeight: '900', paddingHorizontal: 8, paddingVertical: 5, borderRadius: 10, backgroundColor: '#DCFCE7' },
  pending: { color: '#9A6B00', fontSize: 12, fontWeight: '900', paddingHorizontal: 8, paddingVertical: 5, borderRadius: 10, backgroundColor: '#FEF3C7' },
});

const sosFlowStyles = StyleSheet.create({
  full: { flex: 1, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 24 },
  closeButton: { position: 'absolute', top: 56, left: 20, width: 44, height: 44, borderRadius: 22, alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(255,255,255,0.16)' },
  countLabel: { color: 'rgba(255,255,255,0.72)', fontSize: 13, fontWeight: '800', letterSpacing: 3, marginBottom: 24, textTransform: 'uppercase' },
  countRingWrap: { width: 160, height: 160, alignItems: 'center', justifyContent: 'center', marginBottom: 24 },
  countNumber: { position: 'absolute', color: '#FFFFFF', fontSize: 80, fontWeight: '900', lineHeight: 88 },
  countTitle: { color: 'rgba(255,255,255,0.84)', fontSize: 16, fontWeight: '800', textAlign: 'center' },
  countCopy: { color: 'rgba(255,255,255,0.54)', fontSize: 14, fontWeight: '600', lineHeight: 20, textAlign: 'center', marginTop: 8, marginBottom: 36, paddingHorizontal: 8 },
  cancelButton: { height: 56, paddingHorizontal: 40, borderRadius: 16, borderWidth: 1, borderColor: 'rgba(255,255,255,0.25)', alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(255,255,255,0.15)' },
  cancelText: { color: '#FFFFFF', fontSize: 16, fontWeight: '800' },
  activatingIcon: { width: 94, height: 94, borderRadius: 30, alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(255,255,255,0.13)' },
  activatingEmoji: { color: '#FFFFFF', fontSize: 28, fontWeight: '900', letterSpacing: 1 },
  activeScreen: { flex: 1, backgroundColor: '#0A0F1E' },
  activeTop: { minHeight: 96, paddingTop: 54, paddingHorizontal: 20, paddingBottom: 12, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  activeStatus: { flexDirection: 'row', alignItems: 'center', gap: 9 },
  liveDot: { width: 11, height: 11, borderRadius: 6, backgroundColor: '#EF4444' },
  activeStatusText: { color: '#FFFFFF', fontSize: 14, fontWeight: '900', letterSpacing: 1.1 },
  resolvePill: { paddingHorizontal: 14, paddingVertical: 8, borderRadius: 16, borderWidth: 1, borderColor: 'rgba(255,255,255,0.14)' },
  resolveText: { color: 'rgba(255,255,255,0.58)', fontSize: 12, fontWeight: '800' },
  activeContent: { paddingHorizontal: 20, paddingBottom: 28 },
  activeSiren: { width: 82, height: 82, borderRadius: 26, alignSelf: 'center', alignItems: 'center', justifyContent: 'center', marginTop: 4, backgroundColor: '#EF4444', shadowColor: '#EF4444', shadowOpacity: 0.38, shadowRadius: 22, shadowOffset: { width: 0, height: 8 }, elevation: 6 },
  sirenEmoji: { color: '#FFFFFF', fontSize: 24, fontWeight: '900' },
  activeTitle: { color: '#FFFFFF', fontSize: 26, fontWeight: '900', textAlign: 'center', marginTop: 15 },
  activeCopy: { color: 'rgba(255,255,255,0.54)', fontSize: 14, fontWeight: '700', textAlign: 'center', marginTop: 6, marginBottom: 24 },
  sectionLabel: { color: 'rgba(255,255,255,0.42)', fontSize: 11, fontWeight: '900', letterSpacing: 1.7, marginTop: 8, marginBottom: 10 },
  actionCard: { borderRadius: 20, backgroundColor: 'rgba(255,255,255,0.06)', borderWidth: 1, borderColor: 'rgba(255,255,255,0.08)', overflow: 'hidden' },
  actionRow: { minHeight: 54, flexDirection: 'row', alignItems: 'center', gap: 13, paddingHorizontal: 16, borderBottomWidth: 1, borderBottomColor: 'rgba(255,255,255,0.04)' },
  actionIcon: { width: 32, height: 32, borderRadius: 16, alignItems: 'center', justifyContent: 'center' },
  actionText: { flex: 1, color: '#FFFFFF', fontSize: 14, fontWeight: '800' },
  timelineCard: { borderRadius: 20, backgroundColor: 'rgba(255,255,255,0.04)', borderWidth: 1, borderColor: 'rgba(255,255,255,0.06)', padding: 16 },
  timelineRow: { flexDirection: 'row', alignItems: 'center', gap: 10, minHeight: 30 },
  timelineTime: { width: 40, color: '#EF4444', fontSize: 11, fontWeight: '900' },
  timelineDot: { width: 4, height: 4, borderRadius: 2, backgroundColor: 'rgba(255,255,255,0.28)' },
  timelineText: { flex: 1, color: 'rgba(255,255,255,0.64)', fontSize: 12, fontWeight: '700' },
  bottomActions: { paddingHorizontal: 20, paddingTop: 14, paddingBottom: 28, backgroundColor: '#0A0F1E' },
  callParentButton: { height: 58, borderRadius: 18, backgroundColor: '#0B8FFF', flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 10, shadowColor: '#0B8FFF', shadowOpacity: 0.34, shadowRadius: 18, shadowOffset: { width: 0, height: 8 }, elevation: 4 },
  callParentText: { color: '#FFFFFF', fontSize: 17, fontWeight: '900' },
  markResolvedText: { color: 'rgba(255,255,255,0.48)', fontSize: 14, fontWeight: '800', textAlign: 'center', paddingTop: 16 },
});

function LegacyHomeScreen() {
  const { user, logout } = useAuthStore();
  const role = (user?.role || '').toLowerCase().trim();
  const router = useRouter();

  const isGuardian = ['guardian', 'parent', 'parents', 'caregiver'].includes(role);
  const isChild = ['child', 'kid', 'kids', 'children'].includes(role);
  const isWoman = ['woman', 'women'].includes(role);
  const isFamilyMember = ['family', 'family_member', 'member'].includes(role);
  const isProtectedFamily = ['senior', 'elderly'].includes(role);

  // Child role gets a dedicated full-screen minimalist layout (no shared greeting header).
  // Guardian/Women keep the existing header intact.
  if (isChild || isFamilyMember) {
    return <ChildDashboard />;
  }
  if (isWoman) {
    return <ChildDashboard />;
  }
  if (isProtectedFamily) {
    return <ReferenceProtectedDashboard mode={role} />;
  }
  if (isGuardian) {
    return <ReferenceHomeDashboard />;
  }

  return (
    <SafeAreaView style={styles.safe} edges={['top']}>
      {/* FIXED HEADER */}
      <View style={styles.fixedHeader}>
        <View style={{ flex: 1, flexShrink: 1, marginRight: 12 }}>
          <Text style={styles.greeting} numberOfLines={1} ellipsizeMode="tail">
            {getGreeting()}, {user?.full_name || user?.email?.split('@')[0] || 'there'}
          </Text>
          <View style={styles.profileBadge}>
            <Ionicons name={(BADGE[role] || BADGE.guardian).icon} size={14} color={colors.primary} />
            <Text style={styles.profileText}>{(BADGE[role] || BADGE.guardian).label}</Text>
          </View>
        </View>
        <TouchableOpacity onPress={logout} testID="logout-btn"
          style={{ backgroundColor: colors.critical, paddingHorizontal: 12, paddingVertical: 6, borderRadius: 8, flexShrink: 0 }}>
          <Text style={{ color: '#fff', fontWeight: '700', fontSize: 13 }}>Logout</Text>
        </TouchableOpacity>
      </View>

      {/* DPDP — Privacy & My Data */}
      <TouchableOpacity
        testID="home-privacy-row"
        onPress={() => router.push('/privacy')}
        style={{ flexDirection: 'row', alignItems: 'center', padding: 14,
                 marginHorizontal: 16, marginTop: 4, marginBottom: 8,
                 borderRadius: 12, backgroundColor: '#fff',
                 borderWidth: 1, borderColor: '#e4e7eb' }}>
        <Text style={{ fontSize: 18, marginRight: 12 }}>🔒</Text>
        <View style={{ flex: 1 }}>
          <Text style={{ fontSize: 14, fontWeight: '700', color: '#1a1f2e' }}>
            Privacy & My Data (DPDP)
          </Text>
          <Text style={{ fontSize: 12, color: '#6b7280' }}>
            View, download, manage what we know about you
          </Text>
        </View>
        <Text style={{ fontSize: 18, color: '#9ca3af' }}>›</Text>
      </TouchableOpacity>

      {/* Role-based dashboard rendering */}
      {isWoman ? <WomenDashboard /> : <GuardianHomeDashboard />}

    </SafeAreaView>
  );
}

// =====================================================================
// SHARED: Greeting header, SOS button, SOS modals
// =====================================================================

function getGreeting() {
  const h = new Date().getHours();
  if (h < 12) return 'Good Morning';
  if (h < 18) return 'Good Afternoon';
  return 'Good Evening';
}

function GreetingHeader({ testID }: { testID?: string }) {
  const { user, logout } = useAuthStore();
  const role = (user?.role || '').toLowerCase();
  const badge = BADGE[role] || BADGE.guardian;
  const greeting = getGreeting();
  const tapTs = useRef<number[]>([]);
  const { activate } = useEmergencyStore();
  const [otaChecking, setOtaChecking] = React.useState(false);
  const [otaStatus, setOtaStatus] = React.useState<string | null>(null);

  const handleHiddenTap = async () => {
    const now = Date.now();
    tapTs.current = [...tapTs.current.filter((t) => now - t < HIDDEN_TAP_WINDOW), now];
    if (tapTs.current.length >= HIDDEN_TAP_COUNT) {
      tapTs.current = [];
      Vibration.vibrate([0, 100, 50, 100, 50, 100]);
      const result = await triggerSilentSOS('1234', 'hidden_tap');
      if (result.success && result.eventId) activate(result.eventId, 'hidden_tap');
      else if (result.error && result.error !== 'offline_queued') Alert.alert('Error', result.error);
    }
  };

  const checkOTA = async () => {
    if (otaChecking) return;
    setOtaChecking(true);
    setOtaStatus('Checking…');
    try {
      const Updates: any = await import('expo-updates');
      if (__DEV__) {
        setOtaStatus('Dev mode — OTA disabled');
      } else {
        const check = await Updates.checkForUpdateAsync();
        if (!check.isAvailable) {
          setOtaStatus('✓ App is up to date');
        } else {
          setOtaStatus('Downloading new update…');
          const result = await Updates.fetchUpdateAsync();
          if (result.isNew) {
            setOtaStatus('Applying update…');
            await Updates.reloadAsync();
          } else {
            setOtaStatus('✓ Already have latest');
          }
        }
      }
    } catch (e: any) {
      setOtaStatus(`OTA error: ${e?.message || 'unknown'}`);
    } finally {
      setOtaChecking(false);
      setTimeout(() => setOtaStatus(null), 4000);
    }
  };

  return (
    <View>
      <View style={styles.header}>
        <View style={{ flex: 1 }}>
          <TouchableOpacity onPress={handleHiddenTap} activeOpacity={1} testID={testID || 'hidden-sos-trigger'}>
            <Text style={styles.greeting}>{greeting}, {user?.full_name || user?.email?.split('@')[0] || 'there'}</Text>
          </TouchableOpacity>
          <View style={styles.profileBadge}>
            <Ionicons name={badge.icon} size={16} color={colors.primary} />
            <Text style={styles.profileText}>{badge.label}</Text>
          </View>
        </View>
        <TouchableOpacity onPress={logout} style={styles.logoutBtn} testID="logout-btn">
          <View style={{ flexDirection: 'row', alignItems: 'center', backgroundColor: 'rgba(239,68,68,0.15)', paddingHorizontal: 10, paddingVertical: 6, borderRadius: 8 }}>
            <Ionicons name="log-out-outline" size={18} color={colors.critical} />
            <Text style={{ color: colors.critical, fontSize: 12, fontWeight: '700', marginLeft: 4 }}>Sign Out</Text>
          </View>
        </TouchableOpacity>
      </View>

      {/* Role debug banner + OTA update check (matches reference UI) */}
      <TouchableOpacity
        onPress={checkOTA}
        activeOpacity={0.7}
        style={{
          backgroundColor: 'rgba(99,102,241,0.15)',
          borderColor: 'rgba(99,102,241,0.35)',
          borderWidth: 1,
          borderRadius: 8,
          paddingHorizontal: 10,
          paddingVertical: 8,
          marginTop: 4,
          marginBottom: 12,
        }}
        testID="role-debug-banner"
      >
        <Text style={{ color: '#FBBF24', fontSize: 12, fontWeight: '700' }}>
          Role: {role || 'unknown'}
        </Text>
        <Text style={{ color: '#94A3B8', fontSize: 10, marginTop: 1 }} numberOfLines={1}>
          parsed={role} | view={role} | email={user?.email || '—'}
        </Text>
        <Text style={{ color: '#FBBF24', fontSize: 11, fontWeight: '700', marginTop: 2 }}>
          {otaChecking ? '⟳ ' : '⇣ '}{otaStatus || 'Tap to Check for OTA Update'}
        </Text>
      </TouchableOpacity>
    </View>
  );
}

function EmergencyBanner() {
  const { isActive, isTriggering } = useEmergencyStore();
  const [showCancelModal, setShowCancelModal] = useState(false);
  const pulseAnim = useRef(new Animated.Value(1)).current;

  useEffect(() => {
    if (!isActive) return;
    const p = Animated.loop(Animated.sequence([
      Animated.timing(pulseAnim, { toValue: 0.4, duration: 800, useNativeDriver: true }),
      Animated.timing(pulseAnim, { toValue: 1, duration: 800, useNativeDriver: true }),
    ]));
    p.start();
    return () => p.stop();
  }, [isActive]);

  if (!isActive && !isTriggering) return null;

  return (
    <>
      {isActive && (
        <TouchableOpacity style={styles.emergencyBanner} onPress={() => setShowCancelModal(true)} testID="emergency-active-banner" activeOpacity={0.8}>
          <Animated.View style={[styles.emergencyPulse, { opacity: pulseAnim }]} />
          <View style={styles.emergencyInfo}>
            <Text style={styles.emergencyTitle}>EMERGENCY ACTIVE</Text>
            <Text style={styles.emergencySub}>Live tracking enabled</Text>
            <Text style={styles.emergencyAction}>Cancel with PIN</Text>
          </View>
          <Ionicons name="close-circle" size={28} color={colors.white} />
        </TouchableOpacity>
      )}
      {isTriggering && !isActive && (
        <View style={styles.triggeringBanner} testID="sos-triggering-banner">
          <Ionicons name="radio" size={20} color={colors.warning} />
          <Text style={styles.triggeringText}>Sending SOS...</Text>
        </View>
      )}
      <CancelModal visible={showCancelModal} onClose={() => setShowCancelModal(false)} />
    </>
  );
}

function SOSButton() {
  const { isActive, isTriggering, activate, setTriggering } = useEmergencyStore();
  const [showConfirm, setShowConfirm] = useState(false);
  const [pin, setPin] = useState('1234');
  const [showCancel, setShowCancel] = useState(false);

  const handleTrigger = async () => {
    setShowConfirm(false);
    setTriggering(true);
    const result = await triggerSilentSOS(pin, 'manual_button');
    setTriggering(false);
    if (result.success && result.eventId) activate(result.eventId, 'manual_button');
    else if (result.error && result.error !== 'offline_queued') Alert.alert('Error', result.error);
  };

  return (
    <>
      <TouchableOpacity
        style={[styles.sosBtn, isActive && styles.sosBtnActive]}
        onPress={() => { if (isActive) setShowCancel(true); }}
        onLongPress={() => { if (!isActive) { Vibration.vibrate([0, 100, 50, 100]); setShowConfirm(true); } }}
        delayLongPress={1500}
        disabled={isTriggering}
        testID="sos-trigger-btn"
      >
        <Ionicons name={isActive ? 'pulse' : 'alert-circle'} size={28} color={isActive ? colors.white : colors.critical} />
        <Text style={[styles.sosText, isActive && styles.sosTextActive]}>
          {isActive ? 'SOS ACTIVE — TAP TO CANCEL' : 'SILENT SOS'}
        </Text>
        <Text style={[styles.sosHint, isActive && styles.sosHintActive]}>
          {isActive ? 'Tap to enter cancel PIN' : 'Long press 1.5s or shake phone 3x'}
        </Text>
      </TouchableOpacity>

      {/* Confirm Modal */}
      <Modal visible={showConfirm} transparent animationType="fade">
        <View style={styles.modalOverlay}>
          <View style={styles.modalCard} testID="sos-confirm-modal">
            <Ionicons name="alert-circle" size={48} color={colors.critical} />
            <Text style={styles.modalTitle}>Trigger Silent SOS?</Text>
            <Text style={styles.modalDesc}>Your guardians will be alerted IMMEDIATELY with your location.</Text>
            <Text style={styles.modalLabel}>Set Cancel PIN (4 digits)</Text>
            <TextInput style={styles.pinInput} value={pin} onChangeText={setPin} keyboardType="numeric" maxLength={4} secureTextEntry placeholder="1234" placeholderTextColor={colors.textMuted} testID="sos-pin-input" />
            <View style={styles.modalBtns}>
              <TouchableOpacity style={styles.modalCancelBtn} onPress={() => setShowConfirm(false)} testID="sos-dismiss-btn">
                <Text style={styles.modalCancelText}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity style={[styles.modalConfirmBtn, isTriggering && { opacity: 0.6 }]} onPress={handleTrigger} disabled={isTriggering} testID="sos-confirm-btn">
                <Text style={styles.modalConfirmText}>{isTriggering ? 'Sending...' : 'SEND SOS'}</Text>
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>

      <CancelModal visible={showCancel} onClose={() => setShowCancel(false)} />
    </>
  );
}

function CancelModal({ visible, onClose }: { visible: boolean; onClose: () => void }) {
  const [pin, setPin] = useState('');
  const [loading, setLoading] = useState(false);
  const { deactivate, eventId } = useEmergencyStore();

  const handle = async () => {
    if (pin.length < 4) { Alert.alert('Error', 'Enter 4-digit PIN'); return; }
    setLoading(true);
    const result = await cancelSOS(pin, eventId);
    setLoading(false);
    if (result.success) {
      deactivate();
      setPin('');
      onClose();
      Alert.alert('Safe', 'Emergency cancelled.');
    } else {
      Alert.alert('Wrong PIN', result.error || 'Incorrect PIN. Try again.');
    }
  };

  return (
    <Modal visible={visible} transparent animationType="fade">
      <View style={styles.modalOverlay}>
        <View style={styles.modalCard} testID="cancel-sos-modal">
          <Ionicons name="shield-checkmark" size={48} color={colors.safe} />
          <Text style={styles.modalTitle}>Cancel Emergency?</Text>
          <Text style={styles.modalDesc}>Enter your PIN to confirm you are safe.</Text>
          <TextInput style={styles.pinInput} value={pin} onChangeText={setPin} keyboardType="numeric" maxLength={4} secureTextEntry placeholder="Enter PIN" placeholderTextColor={colors.textMuted} testID="cancel-pin-input" />
          <View style={styles.modalBtns}>
            <TouchableOpacity style={styles.modalCancelBtn} onPress={() => { setPin(''); onClose(); }} disabled={loading}>
              <Text style={styles.modalCancelText}>Back</Text>
            </TouchableOpacity>
            <TouchableOpacity style={[styles.modalSafeBtn, loading && { opacity: 0.6 }]} onPress={handle} disabled={loading} testID="cancel-confirm-btn">
              <Text style={styles.modalConfirmText}>{loading ? 'Cancelling...' : "I'm Safe"}</Text>
            </TouchableOpacity>
          </View>
        </View>
      </View>
    </Modal>
  );
}

function ActionCard({ icon, label, color, onPress, testID }: any) {
  return (
    <TouchableOpacity style={styles.actionCard} onPress={onPress} testID={testID}>
      <View style={[styles.actionIcon, { backgroundColor: color + '20' }]}>
        <Ionicons name={icon} size={24} color={color} />
      </View>
      <Text style={styles.actionLabel}>{label}</Text>
    </TouchableOpacity>
  );
}

// =====================================================================
// CHILD DASHBOARD — Step-1 Core Safety UX (SOS + GPS only)
// 80%-screen "HOLD FOR SOS" button. 1s to trigger, 3s to cancel.
// =====================================================================


const SOS_HOLD_MS = 2000;
const CANCEL_HOLD_MS = 3000;
const DEFAULT_CANCEL_PIN = '1234';
const LOCATION_REFRESH_MS = 15000;
const REVERSE_GEOCODE_INTERVAL_MS = 60_000; // re-geocode at most every 60s
const SLIP_GRACE_MS = 150;                  // finger-slip tolerance
const RETRY_INTERVAL_MS = 3000;             // network retry cadence
const SMS_FALLBACK_AFTER_MS = 30_000;       // 30s of failed retries → SMS fallback

// Module-level guard for ChildDashboard's location loop. A fast re-mount
// (e.g. tab switch + back) was previously stacking a second 15s interval,
// causing duplicate `POST /geofence/location-update`. With this guard,
// only ONE loop runs across the process lifetime.
let _childLocLoopActive = false;
let _childLocInterval: ReturnType<typeof setInterval> | null = null;
let _childLocConsumers = 0;
const _childLocSubscribers: Set<(state: { ts: number | null; err: string | null; area: string | null }) => void> = new Set();
let _childLocSnapshot: { ts: number | null; err: string | null; area: string | null } = { ts: null, err: null, area: null };
let _childLastGeocodeAt = 0;
let _childLastGeocodeCoords: { lat: number; lng: number } | null = null;

function _emitChildLoc() {
  _childLocSubscribers.forEach((cb) => { try { cb(_childLocSnapshot); } catch {} });
}

async function _childLocReverseGeocode(lat: number, lng: number) {
  const now = Date.now();
  if (now - _childLastGeocodeAt < REVERSE_GEOCODE_INTERVAL_MS) {
    const prev = _childLastGeocodeCoords;
    if (prev && Math.abs(prev.lat - lat) < 0.005 && Math.abs(prev.lng - lng) < 0.005) return;
  }
  _childLastGeocodeAt = now;
  _childLastGeocodeCoords = { lat, lng };
  try {
    const results = await Location.reverseGeocodeAsync({ latitude: lat, longitude: lng });
    const r = results?.[0];
    if (!r) return;
    const name = r.district || r.city || r.subregion || r.region || r.name || null;
    if (name) {
      _childLocSnapshot = { ..._childLocSnapshot, area: name };
      _emitChildLoc();
    }
  } catch {}
}

async function _childLocFetchOnce() {
  try {
    const { status } = await Location.requestForegroundPermissionsAsync();
    if (status !== 'granted') {
      _childLocSnapshot = { ..._childLocSnapshot, err: 'permission_denied' };
      _emitChildLoc();
      return;
    }
    const loc = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
    const lat = loc.coords.latitude;
    const lng = loc.coords.longitude;
    _childLocSnapshot = { ts: Date.now(), err: null, area: _childLocSnapshot.area };
    _emitChildLoc();
    _childLocReverseGeocode(lat, lng);
    // Backend applies 60s breach cooldown — but to be safe, this loop is
    // singleton-guarded so we never POST twice from the same process.
    try {
      emergencyService.geofenceLocationUpdate(lat, lng).catch(() => {});
    } catch {}
  } catch {
    _childLocSnapshot = { ..._childLocSnapshot, err: 'unavailable' };
    _emitChildLoc();
  }
}

function _childLocAttach(cb: (s: typeof _childLocSnapshot) => void) {
  _childLocSubscribers.add(cb);
  _childLocConsumers += 1;
  // Emit current snapshot to the late subscriber.
  cb(_childLocSnapshot);
  if (!_childLocLoopActive) {
    _childLocLoopActive = true;
    console.log('[LOCATION_WATCHER] child geofence loop singleton — starting');
    _childLocFetchOnce();
    _childLocInterval = setInterval(_childLocFetchOnce, LOCATION_REFRESH_MS);
  } else {
    console.log(`[LOCATION_WATCHER] child geofence loop reused (consumers=${_childLocConsumers})`);
  }
}

function _childLocDetach(cb: (s: typeof _childLocSnapshot) => void) {
  _childLocSubscribers.delete(cb);
  _childLocConsumers = Math.max(0, _childLocConsumers - 1);
  if (_childLocConsumers === 0 && _childLocInterval) {
    console.log('[LOCATION_WATCHER] child geofence loop singleton — stopping');
    clearInterval(_childLocInterval);
    _childLocInterval = null;
    _childLocLoopActive = false;
  }
}

function ChildDashboard() {
  const router = useRouter();
  const { logout, profileMode } = useAuthStore();
  const { isActive, isTriggering, activate, deactivate, setTriggering, eventId } = useEmergencyStore();
  const isWomanMode = profileMode === 'women';
  const isSeniorMode = profileMode === 'senior';
  const isFamilyMode = profileMode === 'family';
  const isCareMode = isWomanMode || isSeniorMode;
  const primaryGuardianName = isSeniorMode ? 'Priya' : isWomanMode ? 'Priya' : 'Mom';
  const primaryGuardianRole = isSeniorMode ? 'Daughter' : isWomanMode ? 'Mother' : 'Parent';
  const secondaryGuardianName = isSeniorMode ? 'Rajesh' : isWomanMode ? 'Rajesh' : 'Dad';
  const secondaryGuardianRole = isSeniorMode ? 'Son' : isWomanMode ? 'Father' : 'Co-Parent';
  const showSafeWalkBanner = isWomanMode;
  const secondaryActionLabel = isWomanMode ? 'ETA Share' : isSeniorMode ? 'Medicine' : 'Safe Walk';
  const [dashboardCheckedIn, setDashboardCheckedIn] = useState(false);
  const [showUnifiedSOSFlow, setShowUnifiedSOSFlow] = useState(false);

  // ── Check-in pending state ──
  const [pendingCheckIn, setPendingCheckIn] = useState<{
    check_in_id: string;
    responding: boolean;
  } | null>(null);

  const handleChildSSE = useCallback((eventType: string, payload: any) => {
    console.log('[CHILD_SSE]', eventType, payload);
    if (eventType === 'checkin_pending') {
      console.log('[CHECKIN_PENDING_RECEIVED]', payload.check_in_id);
      setPendingCheckIn({ check_in_id: payload.check_in_id, responding: false });
    }
    if (eventType === 'checkin_expired' || eventType === 'checkin_cancelled') {
      setPendingCheckIn(null);
    }
  }, []);

  useChildSSE(handleChildSSE);

  // Auto-expire banner after 90s if SSE checkin_expired is missed
  useEffect(() => {
    if (!pendingCheckIn) return;
    const timer = setTimeout(() => {
      console.log('[CHECKIN_BANNER_EXPIRED] auto-dismissed after 90s');
      setPendingCheckIn(null);
    }, 90000);
    return () => clearTimeout(timer);
  }, [pendingCheckIn?.check_in_id]);

  const respondToCheckIn = async (response: 'safe' | 'help') => {
    if (!pendingCheckIn?.check_in_id) return;
    setPendingCheckIn(prev => prev ? { ...prev, responding: true } : null);
    try {
      console.log('[CHECKIN_RESPOND]', response, pendingCheckIn.check_in_id);
      await checkInService.respond(pendingCheckIn.check_in_id, response);
      console.log('[CHECKIN_RESPOND_DONE]', response);
      setPendingCheckIn(null);
    } catch (e: any) {
      console.error('[CHECKIN_RESPOND_FAILED]', e?.message);
      setPendingCheckIn(prev => prev ? { ...prev, responding: false } : null);
      Alert.alert('Error', 'Could not send response. Please try again.');
    }
  };

  // ── Location state ──
  const [locUpdatedAt, setLocUpdatedAt] = useState<number | null>(null);
  const [locError, setLocError] = useState<string | null>(null);
  const [areaName, setAreaName] = useState<string | null>(null);
  const [, setTick] = useState(0);

  // Subscribe to the singleton location loop. ONE 15s `setInterval`
  // fires across the whole app, even if ChildDashboard re-mounts.
  // Previously, a fast remount (tab switch and back) stacked a second
  // interval, doubling `POST /geofence/location-update`.
  useEffect(() => {
    const cb = (s: { ts: number | null; err: string | null; area: string | null }) => {
      setLocUpdatedAt(s.ts);
      setLocError(s.err);
      if (s.area !== null) setAreaName(s.area);
    };
    _childLocAttach(cb);
    const tickInterval = setInterval(() => setTick((n) => n + 1), 1000);
    return () => {
      _childLocDetach(cb);
      clearInterval(tickInterval);
    };
  }, []);

  const locLabel = (() => {
    if (locError === 'permission_denied') return 'Location permission needed';
    if (!locUpdatedAt) return 'Locating…';
    const secs = Math.max(0, Math.floor((Date.now() - locUpdatedAt) / 1000));
    const ago = secs < 2 ? 'just now' : secs < 60 ? `${secs}s ago` : `${Math.floor(secs / 60)}m ago`;
    const place = areaName || 'GPS locked';
    return `${place} • Updated ${ago}`;
  })();

  // ── Haptic helpers (layered feedback) ──
  const hapticLight = () => { try { Vibration.vibrate(25); } catch {} };
  const hapticStrong = () => { try { Vibration.vibrate([0, 200, 80, 200, 80, 400]); } catch {} };
  const hapticDouble = () => { try { Vibration.vibrate([0, 80, 80, 80]); } catch {} };

  // ── SOS press-and-hold with 150ms slip tolerance ──
  const sosHoldTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const sosGraceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const sosFiredRef = useRef(false);
  const sosInFlightRef = useRef(false);
  const sosHoldStartRef = useRef<number | null>(null); // when current hold session began
  const sosElapsedRef = useRef(0);                     // elapsed across slip-resumed holds
  const sosProgressAnim = useRef(new Animated.Value(0)).current;

  // Retry visibility
  const [retryState, setRetryState] = useState<'idle' | 'sending' | 'retrying' | 'sent'>('idle');
  const retryAttemptsRef = useRef(0);

  // SMS fallback state (30-second safety net)
  const [smsFallbackSent, setSmsFallbackSent] = useState(false);
  const smsFallbackSentRef = useRef(false); // synchronous guard (prevents double-fire during await)
  const sosStartedAtRef = useRef<number | null>(null);
  const [, setTickFallback] = useState(0); // forces re-render each second during retry for countdown
  const [showSosLaunch, setShowSosLaunch] = useState(false);

  const clearSosTimers = useCallback(() => {
    if (sosHoldTimerRef.current) { clearTimeout(sosHoldTimerRef.current); sosHoldTimerRef.current = null; }
    if (sosGraceTimerRef.current) { clearTimeout(sosGraceTimerRef.current); sosGraceTimerRef.current = null; }
  }, []);

  const fullResetSosHold = useCallback(() => {
    clearSosTimers();
    sosHoldStartRef.current = null;
    sosElapsedRef.current = 0;
    sosProgressAnim.stopAnimation();
    sosProgressAnim.setValue(0);
  }, [clearSosTimers, sosProgressAnim]);

  const openUnifiedSOSFlow = useCallback(() => {
    clearSosTimers();
    sosFiredRef.current = true;
    fullResetSosHold();
    setShowUnifiedSOSFlow(true);
  }, [clearSosTimers, fullResetSosHold]);

  // Fires a single SMS fallback (idempotent — guarded by smsFallbackSentRef).
  // Uses current best-known coords; refetches fresh position if not available.
  const fireSmsFallback = useCallback(async () => {
    if (smsFallbackSentRef.current) return;
    smsFallbackSentRef.current = true; // set BEFORE await to block concurrent callers
    try {
      // Try to get a fresh position; fall back to 0,0 if unavailable.
      let lat = 0, lng = 0;
      try {
        const loc = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
        lat = loc.coords.latitude;
        lng = loc.coords.longitude;
      } catch { /* keep 0,0 */ }
      try {
        await emergencyService.smsFallback(lat, lng, 'offline_fallback');
        setSmsFallbackSent(true);
      } catch {
        // Network still down — the marker stays true so we don't spam.
        // Backend is also idempotent (10-min window) so even if this retries later, no dupe.
        setSmsFallbackSent(true);
      }
    } catch {
      // Never throw from fallback
    }
  }, []);

  // The actual "fire SOS" routine — called exactly once per activation cycle.
  const fireSOSWithRetry = useCallback(async () => {
    if (sosInFlightRef.current) return;
    sosInFlightRef.current = true;

    hapticStrong();
    setShowSosLaunch(true);
    setTriggering(true);
    setRetryState('sending');
    retryAttemptsRef.current = 0;
    smsFallbackSentRef.current = false;
    setSmsFallbackSent(false);
    sosStartedAtRef.current = Date.now();

    // Start 1s ticker so UI countdown ("Fallback SMS will be sent in Xs") updates live.
    // Stopped via cleanup in useEffect or when retry succeeds.
    const tickerInterval = setInterval(() => setTickFallback((n) => n + 1), 1000);

    const maybeFireFallback = () => {
      if (smsFallbackSentRef.current) return;
      if (sosStartedAtRef.current == null) return;
      const elapsed = Date.now() - sosStartedAtRef.current;
      if (elapsed >= SMS_FALLBACK_AFTER_MS) {
        fireSmsFallback();
      }
    };

    const attempt = async (): Promise<void> => {
      retryAttemptsRef.current += 1;
      try {
        const result = await triggerSilentSOS(DEFAULT_CANCEL_PIN, 'hold_button');
        if (result.success && result.eventId) {
          await activate(result.eventId, 'hold_button');
          setRetryState('sent');
          sosInFlightRef.current = false;
          clearInterval(tickerInterval);
          return;
        }
        // offline_queued or other failure — continue retrying
        setRetryState('retrying');
        maybeFireFallback();
        setTimeout(attempt, RETRY_INTERVAL_MS);
      } catch {
        setRetryState('retrying');
        maybeFireFallback();
        setTimeout(attempt, RETRY_INTERVAL_MS);
      }
    };

    await attempt();
  }, [activate, setTriggering, fireSmsFallback]);

  useEffect(() => {
    if (!showSosLaunch) return;
    const timer = setTimeout(() => setShowSosLaunch(false), 3000);
    return () => clearTimeout(timer);
  }, [showSosLaunch]);

  const handleSosPressIn = useCallback(() => {
    if (isActive || isTriggering || sosInFlightRef.current || sosFiredRef.current) return;

    // If we're in a slip-grace window, cancel the grace and RESUME where we left off.
    if (sosGraceTimerRef.current) {
      clearTimeout(sosGraceTimerRef.current);
      sosGraceTimerRef.current = null;
    }

    hapticLight();

    const remainingMs = Math.max(0, SOS_HOLD_MS - sosElapsedRef.current);
    sosHoldStartRef.current = Date.now();

    Animated.timing(sosProgressAnim, {
      toValue: 1,
      duration: remainingMs,
      useNativeDriver: false,
    }).start();

    sosHoldTimerRef.current = setTimeout(() => {
      if (sosFiredRef.current || sosInFlightRef.current) return;
      sosFiredRef.current = true;
      openUnifiedSOSFlow();
    }, remainingMs);
  }, [isActive, isTriggering, sosProgressAnim, openUnifiedSOSFlow]);

  const handleSosPressOut = useCallback(() => {
    if (sosFiredRef.current) return;

    if (sosHoldStartRef.current != null) {
      sosElapsedRef.current += Date.now() - sosHoldStartRef.current;
      sosHoldStartRef.current = null;
    }
    sosProgressAnim.stopAnimation();
    if (sosHoldTimerRef.current) { clearTimeout(sosHoldTimerRef.current); sosHoldTimerRef.current = null; }

    if (sosGraceTimerRef.current) clearTimeout(sosGraceTimerRef.current);
    sosGraceTimerRef.current = setTimeout(() => {
      sosGraceTimerRef.current = null;
      fullResetSosHold();
    }, SLIP_GRACE_MS);
  }, [fullResetSosHold, sosProgressAnim]);

  const handleSosTap = useCallback(() => {
    if (isActive || isTriggering || sosInFlightRef.current || sosFiredRef.current) return;
    openUnifiedSOSFlow();
  }, [isActive, isTriggering, openUnifiedSOSFlow]);

  // ── Cancel press-and-hold (3 seconds) — hold-only, no PIN prompt ──
  const cancelHoldTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const cancelGraceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const cancelFiredRef = useRef(false);
  const cancelInFlightRef = useRef(false);
  const cancelHoldStartRef = useRef<number | null>(null);
  const cancelElapsedRef = useRef(0);
  const cancelProgressAnim = useRef(new Animated.Value(0)).current;
  const [cancelling, setCancelling] = useState(false);

  const clearCancelTimers = useCallback(() => {
    if (cancelHoldTimerRef.current) { clearTimeout(cancelHoldTimerRef.current); cancelHoldTimerRef.current = null; }
    if (cancelGraceTimerRef.current) { clearTimeout(cancelGraceTimerRef.current); cancelGraceTimerRef.current = null; }
  }, []);

  const fullResetCancelHold = useCallback(() => {
    clearCancelTimers();
    cancelHoldStartRef.current = null;
    cancelElapsedRef.current = 0;
    cancelProgressAnim.stopAnimation();
    cancelProgressAnim.setValue(0);
  }, [clearCancelTimers, cancelProgressAnim]);

  const handleCancelPressIn = useCallback(() => {
    if (!isActive || cancelInFlightRef.current || cancelFiredRef.current) return;

    if (cancelGraceTimerRef.current) {
      clearTimeout(cancelGraceTimerRef.current);
      cancelGraceTimerRef.current = null;
    }

    hapticLight();
    const remainingMs = Math.max(0, CANCEL_HOLD_MS - cancelElapsedRef.current);
    cancelHoldStartRef.current = Date.now();

    Animated.timing(cancelProgressAnim, {
      toValue: 1,
      duration: remainingMs,
      useNativeDriver: false,
    }).start();

    cancelHoldTimerRef.current = setTimeout(async () => {
      if (cancelFiredRef.current || cancelInFlightRef.current) return;
      cancelFiredRef.current = true;
      cancelInFlightRef.current = true;
      setCancelling(true);
      try {
        const result = await cancelSOS(DEFAULT_CANCEL_PIN, eventId);
        if (result.success) {
          hapticDouble();
          await deactivate();
          setRetryState('idle');
          setSmsFallbackSent(false);
          smsFallbackSentRef.current = false;
          sosStartedAtRef.current = null;
        } else {
          Alert.alert('Cancel Failed', result.error || 'Please try again');
          cancelFiredRef.current = false;
        }
      } catch (e: any) {
        Alert.alert('Cancel Failed', e?.message || 'Please try again');
        cancelFiredRef.current = false;
      } finally {
        cancelInFlightRef.current = false;
        setCancelling(false);
        fullResetCancelHold();
      }
    }, remainingMs);
  }, [isActive, eventId, deactivate, cancelProgressAnim, fullResetCancelHold]);

  const handleCancelPressOut = useCallback(() => {
    if (cancelFiredRef.current) return;

    if (cancelHoldStartRef.current != null) {
      cancelElapsedRef.current += Date.now() - cancelHoldStartRef.current;
      cancelHoldStartRef.current = null;
    }
    cancelProgressAnim.stopAnimation();
    if (cancelHoldTimerRef.current) { clearTimeout(cancelHoldTimerRef.current); cancelHoldTimerRef.current = null; }

    if (cancelGraceTimerRef.current) clearTimeout(cancelGraceTimerRef.current);
    cancelGraceTimerRef.current = setTimeout(() => {
      cancelGraceTimerRef.current = null;
      fullResetCancelHold();
    }, SLIP_GRACE_MS);
  }, [cancelProgressAnim, fullResetCancelHold]);

  // Reset fire/cancel guards when SOS state flips off (e.g. restored state cleared)
  useEffect(() => {
    if (!isActive && !isTriggering) {
      sosFiredRef.current = false;
      sosElapsedRef.current = 0;
      cancelFiredRef.current = false;
      cancelElapsedRef.current = 0;
    }
  }, [isActive, isTriggering]);

  // Cleanup timers on unmount
  useEffect(() => {
    return () => { fullResetSosHold(); fullResetCancelHold(); };
  }, [fullResetSosHold, fullResetCancelHold]);

  // ── ACTIVATED SCREEN (shared Figma/video SOS flow) ──
  if ((isActive || isTriggering) && !showUnifiedSOSFlow) {
    return (
      <ProtectedSOSFlow
        visible
        startPhase={isTriggering ? 'activating' : 'active'}
        triggerSource="protected_dashboard_sos"
        onClose={() => {
          fullResetSosHold();
          fullResetCancelHold();
          sosFiredRef.current = false;
          setShowSosLaunch(false);
          deactivate();
        }}
      />
    );
  }

  // Legacy emergency screen kept below as a fallback reference, but no longer rendered.
  if (false && (isActive || isTriggering) && !showUnifiedSOSFlow) {
    const cancelWidth = cancelProgressAnim.interpolate({ inputRange: [0, 1], outputRange: ['0%', '100%'] });
    const isNetworkIssue = retryState === 'retrying';
    const statusLine = isNetworkIssue
      ? '⚠ Network issue — Retrying…'
      : retryState === 'sending'
      ? 'Sending alert…'
      : 'Alert sent';

    // SMS fallback countdown — only relevant while retrying + before fallback fired
    let fallbackLine: string | null = null;
    const sosStartedAt = sosStartedAtRef.current;
    if (isNetworkIssue && typeof sosStartedAt === 'number') {
      const elapsedSec = Math.floor((Date.now() - Number(sosStartedAt)) / 1000);
      if (smsFallbackSent) {
        fallbackLine = '📡 SMS alert sent to guardians · Still trying to sync…';
      } else {
        const remaining = Math.max(0, Math.ceil((SMS_FALLBACK_AFTER_MS / 1000) - elapsedSec));
        if (remaining > 0) {
          fallbackLine = `Fallback SMS will be sent in ${remaining}s if connection is not restored`;
        }
      }
    } else if (smsFallbackSent) {
      // Rare: SMS was sent, and retry now succeeded — still inform user
      fallbackLine = '📡 SMS alert was sent to guardians';
    }

    return showSosLaunch ? (
      <SafeAreaView style={childStep.launchSafe} edges={['top', 'bottom']} testID="child-sos-launching">
        <View style={childStep.launchCard}>
          <View style={childStep.launchRings}>
            <View style={childStep.launchRingOne} />
            <View style={childStep.launchRingTwo} />
            <View style={childStep.launchPulse}>
              <Text style={childStep.launchSiren}>🚨</Text>
            </View>
          </View>
          <Text style={childStep.launchTitle}>SOS ACTIVATING</Text>
          <Text style={childStep.launchSub}>Notifying guardians now</Text>
          <View style={childStep.launchProgressTrack}>
            <View style={childStep.launchProgressFill} />
          </View>
        </View>
      </SafeAreaView>
    ) : (
      <SafeAreaView style={childStep.activatedSafe} edges={['top', 'bottom']} testID="child-sos-activated">
        <ScrollView style={childStep.activatedScroll} contentContainerStyle={childStep.activatedContent} showsVerticalScrollIndicator={false}>
          <View style={childStep.emergencyHero}>
            <View style={childStep.emergencyRings}>
              <View style={childStep.emergencyRingOne} />
              <View style={childStep.emergencyRingTwo} />
              <View style={childStep.emergencyPulse} />
            </View>
            <Text style={childStep.emergencyEyebrow}>EMERGENCY ACTIVE</Text>
            <Text style={childStep.activatedTitle}>SOS ACTIVATED</Text>
            <Text style={[childStep.activatedSub, isNetworkIssue && childStep.activatedSubWarn]} testID="sos-status-line">{statusLine}</Text>
            <Text style={childStep.activatedSub}>Sharing live location with guardians</Text>
            {areaName ? <Text style={childStep.activatedPlace}>Location: {areaName}</Text> : null}
            {retryState === 'retrying' && retryAttemptsRef.current > 1 ? <Text style={childStep.activatedAttempt}>Attempt {retryAttemptsRef.current}</Text> : null}
            {fallbackLine ? (
              <Text style={[childStep.fallbackLine, smsFallbackSent && childStep.fallbackLineSent]} testID="sos-fallback-line">
                {fallbackLine}
              </Text>
            ) : null}
          </View>

          <Text style={childStep.darkSectionLabel}>ACTIONS TAKEN</Text>
          <View style={childStep.actionsTakenCard}>
            {[
              ['Parent Notified', '#0A84FF'],
              ['Co-Parent Notified', '#0A84FF'],
              ['Emergency Contacts Alerted', '#F59E0B'],
              ['Live Location Shared', '#22C55E'],
              ['Emergency Timeline Started', '#06B6D4'],
              ['AI Monitoring Escalated', '#22C55E'],
            ].map(([label, tone]) => (
              <View key={label} style={childStep.actionTakenRow}>
                <View style={[childStep.actionCheck, { backgroundColor: tone }]}>
                  <Ionicons name="checkmark" size={17} color="#FFFFFF" />
                </View>
                <Text style={childStep.actionTakenText}>{label}</Text>
              </View>
            ))}
          </View>

          <Text style={childStep.darkSectionLabel}>EMERGENCY TIMELINE</Text>
          <View style={childStep.timelineCard}>
            {[
              ['Now', 'SOS Activated by child'],
              ['+0:05', 'Guardian push notification sent'],
              ['+0:10', 'Co-guardian SMS dispatched'],
              ['+0:12', 'Live location stream started'],
              ['+0:18', 'Emergency contacts alerted'],
            ].map(([time, label]) => (
              <View key={time} style={childStep.timelineRow}>
                <Text style={childStep.timelineTime}>{time}</Text>
                <Text style={childStep.timelineText}>{label}</Text>
              </View>
            ))}
          </View>

          <TouchableOpacity activeOpacity={0.86} style={childStep.callParentButton}>
            <Ionicons name="call-outline" size={22} color="#FFFFFF" />
            <Text style={childStep.callParentText}>Call Parent Now</Text>
          </TouchableOpacity>
          <TouchableOpacity activeOpacity={0.82} onPress={deactivate}>
            <Text style={childStep.markResolvedText}>Mark Resolved</Text>
          </TouchableOpacity>
        </ScrollView>
      </SafeAreaView>
    );

    return (
      <SafeAreaView style={childStep.activatedSafe} edges={['top', 'bottom']} testID="child-sos-activated">
        <View style={childStep.activatedInner}>
          <View style={childStep.activatedHeader}>
            <Ionicons name="alert-circle" size={72} color="#FFFFFF" />
            <Text style={childStep.activatedTitle}>SOS ACTIVATED</Text>
            <Text
              style={[childStep.activatedSub, isNetworkIssue && childStep.activatedSubWarn]}
              testID="sos-status-line"
            >
              {statusLine}
            </Text>
            <Text style={childStep.activatedSub}>Sharing location…</Text>
            {areaName ? (
              <Text style={childStep.activatedPlace}>📍 {areaName}</Text>
            ) : null}
            {retryState === 'retrying' && retryAttemptsRef.current > 1 ? (
              <Text style={childStep.activatedAttempt}>Attempt {retryAttemptsRef.current}</Text>
            ) : null}
            {fallbackLine ? (
              <Text
                style={[childStep.fallbackLine, smsFallbackSent && childStep.fallbackLineSent]}
                testID="sos-fallback-line"
              >
                {fallbackLine}
              </Text>
            ) : null}
          </View>

          {isActive && (
            <Pressable
              onPressIn={handleCancelPressIn}
              onPressOut={handleCancelPressOut}
              style={childStep.cancelBtn}
              testID="sos-cancel-hold-btn"
              disabled={cancelling}
            >
              <Animated.View style={[childStep.cancelProgressFill, { width: cancelWidth }]} />
              <View style={childStep.cancelContent}>
                <Ionicons name="shield-checkmark" size={22} color="#FFFFFF" />
                <Text style={childStep.cancelLabel}>
                  {cancelling ? 'CANCELLING…' : 'HOLD 3s TO CANCEL'}
                </Text>
              </View>
            </Pressable>
          )}
        </View>
      </SafeAreaView>
    );
  }

  // ── IDLE SCREEN: big red button ──
  const sosWidth = sosProgressAnim.interpolate({ inputRange: [0, 1], outputRange: ['0%', '100%'] });

  return (
    <SafeAreaView style={childStep.safe} edges={['top', 'bottom']} testID="child-dashboard">
      {/* Minimal top strip: status pill + logout */}
      <View style={[childStep.protectionBar, isCareMode && childStep.womanProtectionBar]}>
        <View style={childStep.protectionDot} />
        <View style={childStep.protectionGlow} />
        <Text style={[childStep.protectionText, isCareMode && childStep.womanProtectionText]}>You Are Protected - AI Active - Guardian Connected</Text>
      </View>

      {/* CHECK-IN PENDING BANNER */}
      {pendingCheckIn && (
        <View style={childStep.checkInBanner}>
          <View style={childStep.checkInBannerHeader}>
            <Ionicons name="time-outline" size={20} color={colors.warning} />
            <Text style={childStep.checkInBannerTitle}>Safety Check</Text>
          </View>
          <Text style={childStep.checkInBannerMsg}>
            Your guardian wants to know you're safe. Please respond.
          </Text>
          <View style={childStep.checkInBannerBtns}>
            <TouchableOpacity
              style={childStep.checkInSafeBtn}
              onPress={() => respondToCheckIn('safe')}
              disabled={pendingCheckIn.responding}
              testID="checkin-safe-btn"
            >
              <Ionicons name="checkmark-circle" size={18} color="#fff" />
              <Text style={childStep.checkInSafeBtnText}>
                {pendingCheckIn.responding ? 'Sending…' : "I'm Safe"}
              </Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={childStep.checkInHelpBtn}
              onPress={() => respondToCheckIn('help')}
              disabled={pendingCheckIn.responding}
              testID="checkin-help-btn"
            >
              <Ionicons name="alert-circle" size={18} color="#fff" />
              <Text style={childStep.checkInHelpBtnText}>Need Help</Text>
            </TouchableOpacity>
          </View>
        </View>
      )}

      {/* BIG RED BUTTON — takes remaining screen */}
      <ScrollView style={childStep.scroll} contentContainerStyle={childStep.scrollContent} showsVerticalScrollIndicator={false}>
        <View style={[childStep.guardianRow, isCareMode && childStep.womanGuardianRow]}>
          <View style={[childStep.guardianCard, isCareMode && childStep.womanGuardianCard]}>
            <Text style={childStep.guardianEmoji}>{isWomanMode ? '👩' : '👩'}</Text>
            <View style={childStep.guardianCopy}>
              <Text style={childStep.guardianName}>{primaryGuardianName}</Text>
              <Text style={[childStep.guardianRole, isCareMode && childStep.womanGuardianRoleBlue]}>{primaryGuardianRole}</Text>
            </View>
            <TouchableOpacity style={childStep.callGreen} activeOpacity={0.86}>
              <Ionicons name="call-outline" size={20} color="#FFFFFF" />
              <Text style={childStep.callText}>Call</Text>
            </TouchableOpacity>
          </View>
          <View style={[childStep.guardianCard, isCareMode && childStep.womanGuardianCard, isCareMode && childStep.womanSecondGuardian]}>
            <Text style={childStep.guardianEmoji}>👨</Text>
            <View style={childStep.guardianCopy}>
              <Text style={childStep.guardianName}>{secondaryGuardianName}</Text>
              <Text style={[childStep.guardianRole, isCareMode && childStep.womanGuardianRoleGreen]}>{secondaryGuardianRole}</Text>
            </View>
            <TouchableOpacity style={childStep.callBlue} activeOpacity={0.86}>
              <Ionicons name="call-outline" size={20} color="#FFFFFF" />
              <Text style={childStep.callText}>Call</Text>
            </TouchableOpacity>
          </View>
        </View>
        {isWomanMode ? (
          <TouchableOpacity activeOpacity={0.86} onPress={() => router.push('/(tabs)/guardian')} style={childStep.startSafeWalkButton}>
            <Text style={childStep.startSafeWalkIcon}>🚶</Text>
            <View>
              <Text style={childStep.startSafeWalkTitle}>Start Safe Walk</Text>
              <Text style={childStep.startSafeWalkSub}>Journey protection</Text>
            </View>
          </TouchableOpacity>
        ) : null}
        <Pressable
          onPress={handleSosTap}
          onPressIn={handleSosPressIn}
          onPressOut={handleSosPressOut}
          style={({ pressed }) => [
            childStep.sosButton,
            isCareMode && childStep.womanSosButton,
            pressed && childStep.sosButtonPressed,
          ]}
          testID="sos-hold-btn"
          accessibilityLabel="Hold for SOS"
          accessibilityRole="button"
        >
          <Animated.View style={[childStep.sosProgressFill, { width: sosWidth }]} />
          <View pointerEvents="none" style={childStep.gridOverlay}>
            {Array.from({ length: 8 }).map((_, index) => <View key={`v-${index}`} style={[childStep.gridV, { left: `${(index + 1) * 12.5}%` }]} />)}
            {Array.from({ length: 8 }).map((_, index) => <View key={`h-${index}`} style={[childStep.gridH, { top: `${(index + 1) * 12.5}%` }]} />)}
            <View style={childStep.ringOne} />
            <View style={childStep.ringTwo} />
            <View style={childStep.ringThree} />
          </View>
          <View style={childStep.sosContent} pointerEvents="none">
            <Text style={childStep.sirenEmoji}>🚨</Text>
            <Text style={childStep.sosLabel}>I NEED HELP</Text>
            <Text style={childStep.sosHint}>Tap anywhere - Hold for 2 seconds</Text>
            <View style={childStep.sosBullets}>
              <Text style={childStep.sosBullet}>• Guardian notified instantly</Text>
              <Text style={childStep.sosBullet}>• Live location shared</Text>
              <Text style={childStep.sosBullet}>• AI emergency monitoring activated</Text>
            </View>
          </View>
        </Pressable>
        <View style={childStep.childActions}>
          <TouchableOpacity style={[childStep.safeButton, dashboardCheckedIn && childStep.safeButtonChecked]} activeOpacity={0.86} onPress={() => setDashboardCheckedIn(true)}>
            <Text style={[childStep.safeButtonText, dashboardCheckedIn && childStep.safeButtonCheckedText]}>{dashboardCheckedIn ? 'Checked In' : "I'm Safe"}</Text>
          </TouchableOpacity>
          <TouchableOpacity onPress={() => router.push('/(tabs)/guardian')} style={[childStep.safeWalkButton, isWomanMode && childStep.etaShareButton, isSeniorMode && childStep.medicineButton]} activeOpacity={0.86}>
            <Text style={childStep.safeButtonText}>{isWomanMode ? '📍 ETA Share' : isSeniorMode ? '💊 Medicine' : 'Safe Walk 🚶'}</Text>
          </TouchableOpacity>
        </View>

      {/* Location line */}
        <View style={childStep.locLine} testID="child-location-line">
          <Ionicons name="location" size={14} color="#64748B" />
          <Text style={childStep.locText}>{locLabel}</Text>
        </View>

      {false ? (
      <TouchableOpacity
        onPress={() => router.push('/(tabs)/journey')}
        style={childStep.journeyLink}
        testID="start-journey-link"
        activeOpacity={0.6}
      >
        <Text style={childStep.journeyLinkText}>Start Journey →</Text>
      </TouchableOpacity>
      ) : null}
      </ScrollView>
      <ProtectedSOSFlow
        visible={showUnifiedSOSFlow}
        triggerSource="protected_dashboard_sos"
        onClose={() => {
          setShowUnifiedSOSFlow(false);
          sosFiredRef.current = false;
          sosInFlightRef.current = false;
          fullResetSosHold();
        }}
      />
    </SafeAreaView>
  );
}



const childStep = StyleSheet.create({
  safe: { flex: 1, backgroundColor: '#F3F7FB' },
  scroll: { flex: 1 },
  scrollContent: { paddingBottom: 20 },
  protectionBar: {
    minHeight: 56,
    backgroundColor: '#15803D',
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    paddingHorizontal: 28,
  },
  protectionDot: { width: 11, height: 11, borderRadius: 6, backgroundColor: '#4ADE80' },
  protectionGlow: { width: 15, height: 15, borderRadius: 8, backgroundColor: '#86EFAC' },
  protectionText: { flex: 1, color: '#FFFFFF', fontSize: 16, fontWeight: '900' },
  womanProtectionBar: { backgroundColor: '#DCFCE7', minHeight: 58 },
  womanProtectionText: { color: '#067A31' },
  guardianRow: { flexDirection: 'row', gap: 12, paddingHorizontal: 16, paddingTop: 16 },
  womanGuardianRow: { gap: 0, paddingHorizontal: 18, paddingTop: 16, borderRadius: 18 },
  guardianCard: {
    flex: 1,
    minHeight: 126,
    borderRadius: 16,
    backgroundColor: '#FFFFFF',
    padding: 14,
    shadowColor: '#0F172A',
    shadowOpacity: 0.08,
    shadowOffset: { width: 0, height: 8 },
    shadowRadius: 16,
    elevation: 3,
  },
  womanGuardianCard: { borderRadius: 0, minHeight: 178, alignItems: 'center', shadowOpacity: 0, elevation: 0 },
  womanSecondGuardian: { borderLeftWidth: 1, borderLeftColor: '#D8E2EE' },
  guardianEmoji: { position: 'absolute', left: 16, top: 17, fontSize: 27 },
  guardianCopy: { marginLeft: 50, minHeight: 48 },
  guardianName: { color: '#06122A', fontSize: 20, fontWeight: '900' },
  guardianRole: { color: '#64748B', fontSize: 13, fontWeight: '700', marginTop: 2 },
  womanGuardianRoleBlue: { color: '#0A84FF' },
  womanGuardianRoleGreen: { color: '#16A34A' },
  callGreen: { height: 50, borderRadius: 16, backgroundColor: '#22C55E', flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8, marginTop: 10 },
  callBlue: { height: 50, borderRadius: 16, backgroundColor: '#0B8CE3', flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8, marginTop: 10 },
  callText: { color: '#FFFFFF', fontSize: 18, fontWeight: '900' },
  startSafeWalkButton: { minHeight: 70, marginHorizontal: 18, marginTop: 16, borderRadius: 16, backgroundColor: '#9333EA', flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 12, shadowColor: '#8B5CF6', shadowOpacity: 0.22, shadowOffset: { width: 0, height: 10 }, shadowRadius: 20, elevation: 4 },
  startSafeWalkIcon: { fontSize: 22 },
  startSafeWalkTitle: { color: '#FFFFFF', fontSize: 18, fontWeight: '900' },
  startSafeWalkSub: { color: '#E9D5FF', fontSize: 13, fontWeight: '700', marginTop: 2 },
  topBar: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 20,
    paddingVertical: 12,
  },
  statusPill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingHorizontal: 12,
    paddingVertical: 6,
    backgroundColor: colors.safe + '15',
    borderRadius: 999,
    borderWidth: 1,
    borderColor: colors.safe + '40',
  },
  statusDot: { width: 8, height: 8, borderRadius: 4, backgroundColor: colors.safe },
  statusText: { fontSize: 13, fontWeight: '700', color: colors.safe, letterSpacing: 0.3 },
  logoutIcon: { padding: 8 },

  // Big red button wrapper — flex:1 so it fills remaining space (~80%)
  sosButton: {
    minHeight: 540,
    marginHorizontal: 16,
    marginTop: 10,
    backgroundColor: '#EF3338',
    borderRadius: 24,
    overflow: 'hidden',
    justifyContent: 'center',
    alignItems: 'center',
    position: 'relative',
    shadowColor: '#EF3338',
    shadowOffset: { width: 0, height: 14 },
    shadowOpacity: 0.22,
    shadowRadius: 18,
    elevation: 8,
  },
  womanSosButton: { minHeight: 322, marginHorizontal: 18, marginTop: 16, borderRadius: 24 },
  sosButtonPressed: {
    backgroundColor: '#DC2626',
    transform: [{ scale: 0.99 }],
  },
  sosProgressFill: {
    position: 'absolute',
    left: 0, top: 0, bottom: 0,
    backgroundColor: '#FFFFFF12',
  },
  gridOverlay: { ...StyleSheet.absoluteFillObject, opacity: 1 },
  gridV: { position: 'absolute', top: 0, bottom: 0, width: 1, backgroundColor: 'transparent' },
  gridH: { position: 'absolute', left: 0, right: 0, height: 1, backgroundColor: 'transparent' },
  ringOne: { position: 'absolute', width: 390, height: 390, borderRadius: 195, borderWidth: 1, borderColor: '#FFFFFF18', left: '50%', top: '50%', marginLeft: -195, marginTop: -195 },
  ringTwo: { position: 'absolute', width: 310, height: 310, borderRadius: 155, borderWidth: 1, borderColor: '#FFFFFF14', left: '50%', top: '50%', marginLeft: -155, marginTop: -155 },
  ringThree: { position: 'absolute', width: 232, height: 232, borderRadius: 116, borderWidth: 1, borderColor: '#FFFFFF10', left: '50%', top: '50%', marginLeft: -116, marginTop: -116 },
  sosContent: {
    alignItems: 'center',
    justifyContent: 'center',
    gap: 12,
    paddingHorizontal: 22,
    width: '100%',
    zIndex: 2,
  },
  sirenEmoji: { fontSize: 44, marginBottom: 6 },
  sosLabel: {
    fontSize: 35,
    lineHeight: 42,
    fontWeight: '900',
    color: '#FFFFFF',
    letterSpacing: 4,
    textAlign: 'center',
  },
  sosHint: {
    fontSize: 15,
    lineHeight: 22,
    fontWeight: '800',
    color: '#FFE2E2',
    textAlign: 'center',
  },
  sosBullets: { alignSelf: 'center', marginTop: 14, gap: 8, width: '82%', maxWidth: 320 },
  sosBullet: { color: '#FFFFFF', fontSize: 15, fontWeight: '800', lineHeight: 22 },
  childActions: { flexDirection: 'row', gap: 12, paddingHorizontal: 16, marginTop: 16 },
  safeButton: { flex: 1, height: 70, borderRadius: 16, alignItems: 'center', justifyContent: 'center', backgroundColor: '#22C55E' },
  safeButtonChecked: { backgroundColor: '#DCFCE7', borderWidth: 1, borderColor: '#86EFAC' },
  safeButtonCheckedText: { color: '#15803D' },
  safeWalkButton: { flex: 1, height: 70, borderRadius: 16, alignItems: 'center', justifyContent: 'center', backgroundColor: '#0B8CE3' },
  etaShareButton: { backgroundColor: '#8B35E8' },
  medicineButton: { backgroundColor: '#F59E0B' },
  safeButtonText: { color: '#FFFFFF', fontSize: 18, fontWeight: '900' },

  // Location line (below button)
  locLine: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    paddingVertical: 6,
  },
  locText: { fontSize: 13, color: colors.textSecondary, fontWeight: '500' },

  // De-emphasized journey link
  journeyLink: {
    alignSelf: 'center',
    paddingHorizontal: 16,
    paddingVertical: 12,
    marginBottom: 8,
  },
  journeyLinkText: {
    fontSize: 13,
    color: colors.textMuted,
    fontWeight: '500',
    textDecorationLine: 'underline',
  },

  // ── ACTIVATED SCREEN ──
  activatedSafe: { flex: 1, backgroundColor: '#070D1C' },
  launchSafe: { flex: 1, backgroundColor: '#FEE2E2', alignItems: 'center', justifyContent: 'center', padding: 24 },
  launchCard: { width: '100%', minHeight: 500, borderRadius: 30, backgroundColor: '#EF2D32', alignItems: 'center', justifyContent: 'center', paddingHorizontal: 24, shadowColor: '#EF4444', shadowOpacity: 0.35, shadowOffset: { width: 0, height: 18 }, shadowRadius: 28, elevation: 8 },
  launchRings: { width: 210, height: 210, alignItems: 'center', justifyContent: 'center', marginBottom: 26 },
  launchRingOne: { position: 'absolute', width: 210, height: 210, borderRadius: 105, borderWidth: 1, borderColor: 'rgba(255,255,255,0.20)' },
  launchRingTwo: { position: 'absolute', width: 150, height: 150, borderRadius: 75, borderWidth: 1, borderColor: 'rgba(255,255,255,0.24)' },
  launchPulse: { width: 96, height: 96, borderRadius: 48, backgroundColor: 'rgba(255,255,255,0.16)', alignItems: 'center', justifyContent: 'center' },
  launchSiren: { fontSize: 54 },
  launchTitle: { color: '#FFFFFF', fontSize: 36, lineHeight: 44, fontWeight: '900', letterSpacing: 2, textAlign: 'center' },
  launchSub: { color: 'rgba(255,255,255,0.88)', fontSize: 18, fontWeight: '800', marginTop: 12 },
  launchProgressTrack: { width: '72%', height: 5, borderRadius: 3, backgroundColor: 'rgba(255,255,255,0.25)', marginTop: 34, overflow: 'hidden' },
  launchProgressFill: { width: '100%', height: 5, borderRadius: 3, backgroundColor: '#FFFFFF' },
  activatedScroll: { flex: 1, backgroundColor: '#070D1C' },
  activatedContent: { paddingBottom: 28 },
  emergencyHero: { minHeight: 248, paddingHorizontal: 24, paddingTop: 42, paddingBottom: 24, overflow: 'hidden', backgroundColor: '#070D1C' },
  emergencyRings: { position: 'absolute', right: -50, top: -105, width: 260, height: 260 },
  emergencyRingOne: { position: 'absolute', width: 230, height: 230, borderRadius: 115, borderWidth: 1.5, borderColor: 'rgba(255,82,82,0.32)', right: 0, top: 0 },
  emergencyRingTwo: { position: 'absolute', width: 150, height: 150, borderRadius: 75, borderWidth: 1.5, borderColor: 'rgba(255,82,82,0.38)', right: 40, top: 40 },
  emergencyPulse: { position: 'absolute', width: 92, height: 92, borderRadius: 46, backgroundColor: '#FF4B55', right: 70, top: 70, shadowColor: '#FF4B55', shadowOpacity: 0.5, shadowOffset: { width: 0, height: 12 }, shadowRadius: 24, elevation: 8 },
  emergencyEyebrow: { color: '#8EA0BB', fontSize: 13, fontWeight: '900', letterSpacing: 1.4, marginTop: 28 },
  darkSectionLabel: { color: '#8EA0BB', fontSize: 14, fontWeight: '900', letterSpacing: 1.4, marginTop: 22, marginBottom: 14, paddingHorizontal: 24 },
  actionsTakenCard: { backgroundColor: '#151B2B', borderTopWidth: 1, borderTopColor: '#20283A', borderBottomWidth: 1, borderBottomColor: '#20283A', paddingHorizontal: 24, paddingVertical: 8 },
  actionTakenRow: { minHeight: 61, flexDirection: 'row', alignItems: 'center', gap: 16 },
  actionCheck: { width: 30, height: 30, borderRadius: 15, alignItems: 'center', justifyContent: 'center' },
  actionTakenText: { color: '#F8FAFC', fontSize: 16, fontWeight: '900' },
  timelineCard: { backgroundColor: '#151B2B', borderTopWidth: 1, borderTopColor: '#20283A', borderBottomWidth: 1, borderBottomColor: '#20283A', paddingHorizontal: 24, paddingVertical: 12 },
  timelineRow: { minHeight: 36, flexDirection: 'row', alignItems: 'center', gap: 28 },
  timelineTime: { width: 40, color: '#0A84FF', fontSize: 14, fontWeight: '900' },
  timelineText: { flex: 1, color: '#CBD5E1', fontSize: 15, fontWeight: '700' },
  callParentButton: { minHeight: 70, marginHorizontal: 24, marginTop: 30, borderRadius: 16, backgroundColor: '#0A8EF0', flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 12 },
  callParentText: { color: '#FFFFFF', fontSize: 18, fontWeight: '900' },
  markResolvedText: { color: '#8EA0BB', textAlign: 'center', fontSize: 16, fontWeight: '800', marginTop: 28 },
  activatedInner: {
    flex: 1,
    paddingHorizontal: 24,
    paddingVertical: 32,
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  activatedHeader: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    gap: 12,
  },
  activatedTitle: {
    fontSize: 40,
    fontWeight: '900',
    color: '#FFFFFF',
    letterSpacing: 3,
    textAlign: 'center',
    marginTop: 16,
  },
  activatedSub: {
    fontSize: 16,
    color: '#FFFFFFCC',
    fontWeight: '600',
    textAlign: 'center',
  },
  activatedCoords: {
    marginTop: 12,
    fontSize: 13,
    color: '#FFFFFF99',
    fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace',
  },
  activatedSubWarn: {
    color: '#FFD36A',
    fontWeight: '800',
  },
  activatedPlace: {
    marginTop: 14,
    fontSize: 15,
    color: '#FFFFFFEE',
    fontWeight: '700',
  },
  activatedAttempt: {
    marginTop: 6,
    fontSize: 12,
    color: '#FFFFFF99',
    fontWeight: '600',
    letterSpacing: 0.5,
  },
  fallbackLine: {
    marginTop: 18,
    marginHorizontal: 8,
    fontSize: 13,
    color: '#FFE4B5',
    fontWeight: '600',
    textAlign: 'center',
    lineHeight: 18,
  },
  fallbackLineSent: {
    color: '#B6F8C9',
    fontWeight: '700',
  },
  cancelBtn: {
    width: '100%',
    height: 72,
    borderRadius: 20,
    backgroundColor: '#FFFFFF22',
    borderWidth: 2,
    borderColor: '#FFFFFF55',
    overflow: 'hidden',
    justifyContent: 'center',
    alignItems: 'center',
    position: 'relative',
  },
  cancelProgressFill: {
    position: 'absolute',
    left: 0, top: 0, bottom: 0,
    backgroundColor: '#FFFFFF33',
  },
  cancelContent: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  cancelLabel: {
    fontSize: 16,
    fontWeight: '900',
    color: '#FFFFFF',
    letterSpacing: 1.5,
  },
  // ── Check-in banner styles ──
  checkInBanner: {
    marginHorizontal: 20,
    marginBottom: 12,
    backgroundColor: colors.warning + '15',
    borderRadius: 16,
    borderWidth: 1,
    borderColor: colors.warning + '40',
    padding: 16,
  },
  checkInBannerHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginBottom: 6,
  },
  checkInBannerTitle: {
    fontSize: 14,
    fontWeight: '800',
    color: colors.warning,
    letterSpacing: 0.5,
  },
  checkInBannerMsg: {
    fontSize: 13,
    color: colors.textSecondary,
    marginBottom: 12,
    lineHeight: 18,
  },
  checkInBannerBtns: {
    flexDirection: 'row',
    gap: 10,
  },
  checkInSafeBtn: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    backgroundColor: colors.safe,
    paddingVertical: 12,
    borderRadius: 12,
  },
  checkInSafeBtnText: {
    fontSize: 14,
    fontWeight: '800',
    color: '#fff',
  },
  checkInHelpBtn: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    backgroundColor: colors.critical,
    paddingVertical: 12,
    borderRadius: 12,
  },
  checkInHelpBtnText: {
    fontSize: 14,
    fontWeight: '800',
    color: '#fff',
  },
});



// =====================================================================
// FIX 1 — DETERMINISTIC STATUS RESOLVER (single source of truth)
// Priority: EMERGENCY > HELP > CHECK_IN_PENDING > LIVE_JOURNEY > SAFE
// =====================================================================
type ResolvedStatus = 'emergency' | 'help' | 'check_in_pending' | 'live_journey' | 'safe';

interface ResolvedChild {
  status: ResolvedStatus;
  label: string;
  icon: keyof typeof Ionicons.glyphMap;
  color: string;
  since: string | null; // ISO timestamp of the triggering event
}

const STATUS_CONFIG: Record<ResolvedStatus, { label: string; icon: keyof typeof Ionicons.glyphMap; color: string }> = {
  emergency:        { label: 'EMERGENCY',        icon: 'warning',          color: colors.critical },
  help:             { label: 'Needs Help!',      icon: 'alert-circle',     color: colors.critical },
  check_in_pending: { label: 'Check-in sent…',   icon: 'time-outline',     color: colors.warning },
  live_journey:     { label: 'Live Journey',     icon: 'navigate-circle',  color: colors.primary },
  safe:             { label: 'Safe',             icon: 'shield-checkmark', color: colors.safe },
};

function resolveChildStatus(
  person: any,
  checkIn: any | undefined,
  sessions: any[],
  alerts: any[],
): ResolvedChild {
  // 1. EMERGENCY — any active SOS alert
  const hasEmergency = alerts.some(
    (a) => a.alert_type === 'emergency_triggered' && a.user_name === person.name,
  );
  if (hasEmergency) {
    const ts = alerts.find((a) => a.alert_type === 'emergency_triggered' && a.user_name === person.name)?.created_at;
    return { ...STATUS_CONFIG.emergency, status: 'emergency', since: ts };
  }

  // 2. HELP — child explicitly requested help (via check-in OR safety_alert)
  if (checkIn?.status === 'help') {
    return { ...STATUS_CONFIG.help, status: 'help', since: checkIn.responded_at };
  }
  const helpAlert = alerts.find(
    (a) => a.alert_type === 'help_requested' && (a.user_name === person.name || a.child_id === person.id),
  );
  if (helpAlert) {
    return { ...STATUS_CONFIG.help, status: 'help', since: helpAlert.created_at };
  }

  // 3. CHECK_IN_PENDING — waiting for child response
  // Check local state first, then fall back to alerts from server
  if (checkIn?.status === 'pending') {
    return { ...STATUS_CONFIG.check_in_pending, status: 'check_in_pending', since: checkIn.created_at };
  }
  const pendingAlert = alerts.find(
    (a) => (a.alert_type || a.type) === 'check_in_pending' && a.user_name === person.name,
  );
  if (pendingAlert) {
    return { ...STATUS_CONFIG.check_in_pending, status: 'check_in_pending', since: pendingAlert.created_at };
  }
  // Also match 'check_in_request' (legacy alert_type)
  const requestAlert = alerts.find(
    (a) => (a.alert_type || a.type) === 'check_in_request' && a.user_name === person.name,
  );
  if (requestAlert) {
    return { ...STATUS_CONFIG.check_in_pending, status: 'check_in_pending', since: requestAlert.created_at };
  }

  // 4. LIVE_JOURNEY — active tracking session
  const liveSession = sessions.find((s) => s.user_name === person.name || s.user_id === person.id);
  if (liveSession || person.hasSession) {
    return { ...STATUS_CONFIG.live_journey, status: 'live_journey', since: liveSession?.started_at || null };
  }

  // 5. SAFE — default
  return { ...STATUS_CONFIG.safe, status: 'safe', since: null };
}

// FIX 3 — DATA FRESHNESS
const STALE_THRESHOLD_MS = 60_000; // data older than 60s = stale
type DataFreshness = 'live' | 'stale' | 'offline';

function getDataFreshness(lastFetchMs: number, isOnline: boolean, sseConnected: boolean): DataFreshness {
  if (!isOnline) return 'offline';
  if (!sseConnected && Date.now() - lastFetchMs > STALE_THRESHOLD_MS) return 'stale';
  return 'live';
}

function timeAgo(ms: number): string {
  const sec = Math.floor((Date.now() - ms) / 1000);
  if (sec < 5) return 'just now';
  if (sec < 60) return `${sec}s ago`;
  const min = Math.floor(sec / 60);
  return `${min}m ago`;
}

// =====================================================================
// GUARDIAN HOME DASHBOARD — child status, live location, alerts, incidents
// =====================================================================

function GuardianHomeDashboard() {
  const { user } = useAuthStore();
  const router = useRouter();
  // Receiver-only gate: guardians/parents/admins do NOT emit SOS, so they don't
  // need microphone / motion-sensor permissions. Keep the same capability map
  // as SafetyProvider + backend silent-sos guard (single source of truth).
  const CAN_TRIGGER_SOS: Record<string, boolean> = {
    child: true, kid: true, woman: true, elderly: true, senior: true,
    guardian: false, parent: false, operator: false, admin: false,
  };
  const canEmit = CAN_TRIGGER_SOS[(user?.role || '').toLowerCase()] === true;
  const [lovedOnes, setLovedOnes] = useState<any[]>([]);
  const [apiAlerts, setApiAlerts] = useState<any[]>([]);
  const [sessions, setSessions] = useState<any[]>([]);
  const [checkInStatuses, setCheckInStatuses] = useState<Record<string, any>>({});
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [checkingIn, setCheckingIn] = useState<string | null>(null);
  const [tab, setTab] = useState<'overview' | 'alerts' | 'history' | 'map'>('overview');
  const [isOnline, setIsOnline] = useState(true);
  const [lastFetchMs, setLastFetchMs] = useState(Date.now());
  const [, forceUpdate] = useState(0); // for ticking "X sec ago"
  // Live location tracking — from Zustand store (SSE → store → UI)
  var liveChildren = useLiveTrackingStore(function(s) { return s.children; });
  var updateChildLoc = useLiveTrackingStore(function(s) { return s.updateChild; });
  // Link child state
  const [showLinkInput, setShowLinkInput] = useState(false);
  const [linkCode, setLinkCode] = useState('');
  const [linkLoading, setLinkLoading] = useState(false);
  const [linkError, setLinkError] = useState<string | null>(null);

  // Zustand Alert Store — persisted, deduped, TTL-managed
  const { alerts: storeAlerts, removeAlert, acknowledgeAlert, pruneExpired } = useAlertStore();

  // Unified Alert Resolver — ONE source of truth
  const allAlerts = mergeAlertSources(apiAlerts, storeAlerts);
  const alertState = resolveAlertState(allAlerts);

  // Fetch debounce — prevent triple-fetch on launch
  const lastFetchRef = useRef(0);
  const FETCH_DEBOUNCE_MS = 3000;

  // FIX: Network status — deduplicate, only log on actual change
  const prevOnlineRef = useRef(true);
  useEffect(() => {
    const unsub = NetInfo.addEventListener((state) => {
      const online = !!(state.isConnected && state.isInternetReachable !== false);
      if (online !== prevOnlineRef.current) {
        prevOnlineRef.current = online;
        setIsOnline(online);
        console.log(`[Guardian] Network: ${online ? 'online' : 'offline'}`);
      }
    });
    return () => unsub();
  }, []);

  // Tick the "last updated" label every 10s
  useEffect(() => {
    const iv = setInterval(() => forceUpdate((n) => n + 1), 10_000);
    return () => clearInterval(iv);
  }, []);

  // TTL auto-pruning — remove expired alerts every 10s
  useEffect(() => {
    const iv = setInterval(() => { pruneExpired(); }, 10_000);
    return () => clearInterval(iv);
  }, [pruneExpired]);

  // HAPTIC: Continuous vibration for unacknowledged EMERGENCY/ESCALATION
  useEffect(() => {
    const isCritical = alertState.type === 'EMERGENCY' || alertState.type === 'ESCALATION';
    const isAcked = alertState.alert?.acknowledged === true;
    if (isCritical && !isAcked) {
      // Repeating vibration pattern: vibrate 1s, pause 0.5s
      Vibration.vibrate([0, 1000, 500, 800, 500], true);
      return () => Vibration.cancel();
    }
    // Stop vibration when acknowledged or resolved
    Vibration.cancel();
  }, [alertState.type, alertState.alert?.acknowledged, alertState.alert?.id]);

  // ── SSE real-time event handler ──
  const handleSSEEvent = useCallback((eventType: string, event: any) => {
    const payload = event.data ?? event;
    console.log(`[Guardian-SSE] ${eventType}`, eventType === 'location_update'
      ? `lat=${payload?.lat} lng=${payload?.lng} child=${payload?.child_name}`
      : (payload?.child_name || ''));
    setLastFetchMs(Date.now()); // SSE event = fresh data

    // Helper: build UnifiedAlert and push to store with dedup
    const pushToStore = (alertType: string, severity: string, message: string, p: any) => {
      const store = useAlertStore.getState();
      const ua: UnifiedAlert = {
        id: p.safety_event_id || p.event_id || p.checkin_id || p.check_in_id || `sse-${Date.now()}`,
        alert_type: alertType,
        severity,
        message,
        user_name: p.child_name || p.user_name,
        child_id: p.child_id || p.user_id,
        child_name: p.child_name || p.user_name,
        created_at: p.timestamp || new Date().toISOString(),
        source: 'sse',
      };
      if (store.isDuplicate(ua.id)) {
        console.log(`[ALERT_DEDUP] Skipped duplicate: ${ua.id} (${alertType})`);
        return;
      }
      store.pushAlert(ua);
      console.log(`[ALERT_PUSHED] ${alertType} id=${ua.id} child=${ua.child_name}`);
    };

    if (eventType === 'location_update') {
      // Push to Zustand store (dedup + trail handled inside store)
      if (typeof updateChildLoc === 'function') {
        updateChildLoc(payload.child_id, {
          lat: payload.lat,
          lng: payload.lng,
          speed: payload.speed_mps || 0,
          zone: payload.zone || '',
          risk: payload.risk_level || 'SAFE',
          ts: payload.timestamp || new Date().toISOString(),
          child_id: payload.child_id,
          child_name: payload.child_name || 'Child',
          child_role: payload.child_role || 'child',
        });
      }
      return;
    }

    if (eventType === 'checkin_pending') {
      setCheckInStatuses((prev) => ({
        ...prev,
        [payload.child_id]: {
          check_in_id: payload.check_in_id,
          status: 'pending',
          created_at: payload.created_at,
        },
      }));
      setApiAlerts((prev) => [
        {
          id: payload.check_in_id,
          alert_type: 'check_in_pending',
          severity: 'medium',
          message: `Safety check sent to ${payload.child_name} — waiting for response.`,
          user_name: payload.child_name,
          created_at: payload.created_at,
          responded: false,
        },
        ...prev,
      ]);
      pushToStore('check_in_pending', 'low', `Check-in sent to ${payload.child_name}`, payload);
    }

    if (eventType === 'checkin_help') {
      setCheckInStatuses((prev) => ({
        ...prev,
        [payload.child_id]: {
          check_in_id: payload.check_in_id,
          status: 'help',
          responded_at: payload.responded_at,
        },
      }));
      setApiAlerts((prev) => [
        {
          id: payload.check_in_id,
          alert_type: 'help_requested',
          severity: 'critical',
          message: `${payload.child_name} needs help! Responded to safety check requesting assistance.`,
          user_name: payload.child_name,
          created_at: payload.responded_at,
        },
        ...prev,
      ]);
      Vibration.vibrate([0, 500, 200, 500]);
      pushToStore('help_requested', 'high', `${payload.child_name} needs help!`, payload);
    }

    if (eventType === 'checkin_safe') {
      setCheckInStatuses((prev) => ({
        ...prev,
        [payload.child_id]: {
          check_in_id: payload.check_in_id,
          status: 'safe',
          responded_at: payload.responded_at,
        },
      }));
      pushToStore('check_in_safe', 'low', `${payload.child_name} confirmed safe`, payload);
    }

    if (eventType === 'emergency_triggered') {
      setApiAlerts((prev) => [
        {
          id: `sos-${Date.now()}`,
          alert_type: 'emergency_triggered',
          severity: 'critical',
          message: `${payload.child_name || 'Child'} triggered SOS!`,
          user_name: payload.child_name,
          created_at: payload.timestamp || new Date().toISOString(),
        },
        ...prev,
      ]);
      pushToStore('emergency_triggered', 'critical', `EMERGENCY: ${payload.child_name || 'Child'} triggered SOS!`, payload);
      Vibration.vibrate([0, 1000, 300, 1000]);
    }

    if (eventType === 'emergency_cancelled' || eventType === 'emergency_resolved') {
      setApiAlerts((prev) =>
        prev.filter((a) => a.alert_type !== 'emergency_triggered' || a.user_name !== payload.child_name),
      );
      const label = eventType === 'emergency_cancelled' ? 'SOS cancelled' : 'Emergency resolved';
      pushToStore('check_in_safe', 'low', `${payload.child_name || 'Child'}: ${label}`, payload);
    }

    if (eventType === 'safety_alert' && payload.type === 'HELP_REQUEST') {
      console.log('[HELP_EVENT_RECEIVED]', payload.child_name, payload.child_id);
      setCheckInStatuses((prev) => ({
        ...prev,
        [payload.child_id]: {
          check_in_id: payload.check_in_id,
          status: 'help',
          responded_at: payload.timestamp,
        },
      }));
      Vibration.vibrate([0, 500, 200, 500, 200, 500]);
      pushToStore('help_requested', 'critical', `${payload.child_name} needs help!`, payload);
    }

    // VOICE_DISTRESS via safety_alert SSE
    if (eventType === 'safety_alert' && payload.type === 'VOICE_DISTRESS') {
      console.log('[VOICE_DISTRESS_RECEIVED]', payload.child_name, 'score:', payload.distress_score);
      Vibration.vibrate([0, 800, 200, 800, 200, 800]);
      const msg = payload.scream_detected
        ? `SCREAM detected from ${payload.child_name}!`
        : `Voice distress from ${payload.child_name}`;
      pushToStore('voice_distress', payload.auto_sos ? 'critical' : 'high', msg, payload);
    }

    // AUTO-ESCALATION: no response in 30s
    if (eventType === 'safety_alert' && payload.type === 'ESCALATION') {
      console.log('[ESCALATION_RECEIVED]', payload.child_name, payload.alert_type);
      Vibration.vibrate([0, 1000, 300, 1000, 300, 1000]);
      pushToStore('auto_escalated', 'critical', payload.message || `${payload.child_name} not responding!`, payload);
    }

    // RISK_UPDATE via SSE — push to risk store. Replaces the
    // 5s `/live/risk` poll for steady-state. The poll is kept (now at
    // 60s) as a safety net for cold-start + dropped SSE.
    //
    // Dedup contract: each emit carries
    //   • `emit_key = "{child_id}:{version}"` — globally unique even
    //     across server restarts / SSE reconnects
    //   • `version` — per-child monotonic counter (atomic Redis INCR)
    // We hard-reject by emit_key first (cheap O(1) Set lookup), then
    // fall back to per-child version comparison so a slow stale event
    // can never make the UI go backwards.
    if (eventType === 'risk_update') {
      const childId = String(payload.child_id || '');
      if (!childId) return;
      const emitKey = String(payload.emit_key || '');
      if (emitKey && _seenRiskEmitKeys.has(emitKey)) return;
      const riskStore = useRiskStore.getState();
      const existing: any = riskStore.entries?.[childId];
      const incoming = Number(payload.version) || 0;
      const prev = Number(existing?.version) || 0;
      if (incoming > 0 && prev > incoming) return;
      if (emitKey) {
        _seenRiskEmitKeys.add(emitKey);
        if (_seenRiskEmitKeys.size > 500) {
          const it = _seenRiskEmitKeys.values();
          for (let i = 0; i < 100; i++) {
            const next = it.next();
            if (next.done || !next.value) break;
            _seenRiskEmitKeys.delete(next.value);
          }
        }
      }
      riskStore.updateRisk({
        child_id: childId,
        child_name: payload.child_name,
        lat: payload.lat,
        lng: payload.lng,
        risk: payload.risk_level || payload.risk,
        score: payload.score,
        factors: payload.factors || [],
        speed_kmh: payload.speed_kmh || 0,
        last_updated: payload.last_updated || new Date().toISOString(),
        version: incoming,
      } as any);
    }

    // ESCALATION_UPDATE via SSE — push to escalation store for live call chain visibility
    if (eventType === 'escalation_update') {
      const { useEscalationStore } = require('@/stores/escalationStore');
      const escalationStore = useEscalationStore.getState();
      escalationStore.setEscalation(payload);
    }

    if (eventType === 'child_linked') {
      fetchData(true);
    }
  }, []);

  const sseConnected = useGuardianSSE(handleSSEEvent);

  // Polling reduced from 5s → 60s as a safety-net only.
  // Steady-state risk updates now arrive via SSE (`risk_update`) from
  // the disciplined `risk_emitter` service. Polling stays around to:
  //   • hydrate on cold start before SSE warms up
  //   • catch any case where SSE drops without us noticing
  useGuardianLocationPolling(true, 60000);

  const freshness = getDataFreshness(lastFetchMs, isOnline, sseConnected);

  const fetchData = useCallback(async (force?: boolean) => {
    // Debounce: skip if fetched < 3s ago (unless forced)
    const now = Date.now();
    if (!force && now - lastFetchRef.current < FETCH_DEBOUNCE_MS) {
      return;
    }
    lastFetchRef.current = now;
    setFetchError(false);
    try {
      const [loRes, alRes, sesRes] = await Promise.all([
        guardianDashboardService.getLovedOnes().catch(() => ({ data: {} })),
        guardianDashboardService.getAlerts(20).catch(() => ({ data: {} })),
        guardianDashboardService.getSessions().catch(() => ({ data: {} })),
      ]);
      const loData = loRes.data || {};
      const monitored = loData.monitored_users || [];
      const seniors = loData.seniors || [];
      const merged = [
        ...monitored.map((m: any) => ({
          id: m.user_id || m.id,
          name: m.name,
          role: m.role || 'child',
          relationship: m.relationship,
          hasSession: m.has_active_session,
          phone: m.phone || null,
          serverStatus: m.status || null,
          location: m.location || null,
          locationType: m.location_type || null,
          lastUpdated: m.last_updated || null,
        })),
        ...seniors.map((s: any) => ({
          id: s.senior_id,
          name: s.name,
          role: 'senior',
          relationship: 'family',
          hasSession: false,
          phone: null,
          serverStatus: null,
          location: null,
          locationType: null,
          lastUpdated: null,
        })),
      ];
      const seen = new Set<string>();
      const deduped = merged.filter((m: any) => {
        if (seen.has(m.name)) return false;
        seen.add(m.name);
        return true;
      });
      setLovedOnes(deduped);

      const alData = alRes.data || {};
      setApiAlerts(alData.alerts || (Array.isArray(alRes.data) ? alRes.data : []));

      const sesData = sesRes.data || {};
      setSessions(sesData.sessions || (Array.isArray(sesRes.data) ? sesRes.data : []));

      // Derive check-in statuses from alerts (single source of truth — no separate API calls)
      const alertsList = alData.alerts || [];
      const statuses: Record<string, any> = {};
      for (const person of deduped) {
        // Help takes priority over pending
        const helpReq = alertsList.find((a: any) => {
          const t = a.alert_type || a.type;
          return t === 'help_requested' && a.user_name === person.name;
        });
        if (helpReq) {
          statuses[person.id] = { status: 'help', responded_at: helpReq.created_at, check_in_id: helpReq.id };
          continue;
        }
        const pending = alertsList.find((a: any) => {
          const t = a.alert_type || a.type;
          return (t === 'check_in_pending' || t === 'check_in_request') && a.user_name === person.name;
        });
        if (pending) {
          statuses[person.id] = { status: 'pending', created_at: pending.created_at, check_in_id: pending.id };
        }
      }
      setCheckInStatuses(statuses);
      setLastFetchMs(Date.now());
    } catch {
      setFetchError(true);
    }
    setLoading(false);
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  // On app foreground → refetch (debounced — won't double-fire with initial useEffect)
  useEffect(function() {
    var sub = AppState.addEventListener('change', function(next) {
      if (next === 'active') {
        console.log('[Guardian] App foregrounded -> fetching latest data');
        fetchData(); // debounce will skip if already fetched < 3s ago
      }
    });
    return function() { sub.remove(); };
  }, [fetchData]);

  const onRefresh = async () => { setRefreshing(true); await fetchData(true); setRefreshing(false); };

  // SB-01 Day 3 — Hermes feedback prompt. Imperative handle so we
  // can `scheduleFor(eventId)` from inside the alert-ack callback
  // without re-renders racing the 30 s timer.
  const feedbackRef = useRef<FeedbackPromptHandle | null>(null);

  // Action bindings — what happens when guardian taps the alert banner
  const handleAlertPress = useCallback((state: AlertState) => {
    if (!state.alert) return;
    // Silence the foreground siren immediately — the guardian engaged.
    import('@/services/pushService').then(m => m.silenceCriticalAlert()).catch(() => {});
    // Mark as acknowledged locally — reduces vibration, changes UI to amber
    acknowledgeAlert(state.alert.id);
    // Report ACK to backend — cancels guardian failsafe timer
    guardianDashboardService.acknowledgeAlert(state.alert.id).catch((err: any) =>
      console.warn('[ALERT_ACK] Backend acknowledge failed:', err?.message)
    );
    // SB-01 Day 3 — schedule the Hermes feedback prompt to surface
    // 30 s after this ack. AsyncStorage dedupes per event_id, so no
    // matter how many times the same alert is re-tapped, the prompt
    // can only fire once. Only schedule for actual SafetyEvents
    // (we use the alert.id as the event_id — same UUID).
    if (state.alert?.id) {
      feedbackRef.current?.scheduleFor(state.alert.id);
    }
    switch (state.type) {
      case 'EMERGENCY':
      case 'VOICE_DISTRESS':
        // Open live map to see child's location
        router.push('/(tabs)/journey');
        break;
      case 'ESCALATION':
      case 'HELP':
        // Call the child or emergency number
        if (state.alert.child_id) {
          const child = lovedOnes.find((p: any) => p.id === state.alert?.child_id);
          if (child?.phone) {
            Linking.openURL(`tel:${child.phone}`);
            return;
          }
        }
        Linking.openURL('tel:112');
        break;
      case 'CHECKIN':
        // Refresh data to show latest check-in status
        fetchData(true);
        break;
    }
  }, [lovedOnes, fetchData, router, acknowledgeAlert]);

  const handleCheckIn = async (childId: string, childName: string) => {
    setCheckingIn(childId);
    try {
      const res = await checkInService.create(childId);
      const ciData = res.data;
      Alert.alert('Check-In Sent', `Safety check sent to ${childName}. You'll be notified when they respond.`);
      setCheckInStatuses(prev => ({
        ...prev,
        [childId]: { check_in_id: ciData.check_in_id, status: 'pending', created_at: ciData.created_at },
      }));
    } catch (e: any) {
      Alert.alert('Error', e.response?.data?.detail || 'Failed to send check-in');
    }
    setCheckingIn(null);
  };

  const handleLinkChild = async () => {
    if (linkCode.length !== 6) { setLinkError('Enter a 6-digit code'); return; }
    setLinkLoading(true);
    setLinkError(null);
    try {
      await guardianLinkService.linkChild(linkCode);
      setShowLinkInput(false);
      setLinkCode('');
      setLinkError(null);
      fetchData(true); // refresh loved ones — forced
    } catch (e: any) {
      const status = e.response?.status;
      const detail = e.response?.data?.detail;
      if (status === 400) setLinkError('Code expired or invalid — try again');
      else if (status === 409) setLinkError('Child already linked');
      else if (status === 403) setLinkError('Cannot link from a child account');
      else setLinkError(detail || 'Something went wrong — try again');
    }
    setLinkLoading(false);
  };

  const fmtTime = (ts: string | null) => toIST(ts);

  return (
    <View style={{ flex: 1 }} testID="guardian-home-dashboard">
      {/* SB-01 Day 3 — Hermes feedback prompt overlay (bottom sheet,
          surfaces 30 s after this guardian acks any SafetyEvent). */}
      <FeedbackPrompt ref={feedbackRef} />
      <ScrollView style={styles.scroll} contentContainerStyle={[styles.content, { paddingBottom: 20 }]}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.primary} />}>

        {/* Safety Services Status — ONLY for users who actually emit SOS (sensors matter for them).
            Guardians/parents/admins are receiver-only — hiding this widget prevents
            unnecessary permission prompts and reduces UI clutter. */}
        {canEmit && <SafetyServicesStatus />}

        {/* HC-01 Day 3 — Wearable health-connect card (onboard) + live vitals strip.
            Onboard card shows only when permissions are NOT yet granted (and not
            in 7-day deny cool-off). Vitals strip shows only when granted. */}
        <WearableConnectCard />
        <VitalsStrip />

        {/* FIX 3 — Live indicator */}
        <View style={uxStyles.freshnessRow} testID="freshness-indicator">
          <View style={[
            uxStyles.freshDot,
            freshness === 'live' && uxStyles.freshDotLive,
            freshness === 'stale' && uxStyles.freshDotStale,
            freshness === 'offline' && uxStyles.freshDotOffline,
          ]} />
          <Text style={uxStyles.freshLabel}>
            {freshness === 'live' ? 'LIVE' : freshness === 'stale' ? 'STALE' : 'OFFLINE'}
          </Text>
          <Text style={uxStyles.freshTimestamp}>
            Updated {timeAgo(lastFetchMs)}
          </Text>
        </View>

        {/* FIX 4 — Offline banner */}
        {!isOnline && (
          <View style={uxStyles.offlineBanner} testID="offline-banner">
            <Ionicons name="cloud-offline-outline" size={18} color={colors.warning} />
            <Text style={uxStyles.offlineText}>No internet — showing cached data</Text>
          </View>
        )}

        {/* Live Escalation Tracker — real-time call chain visibility */}
        <EscalationTracker />

        {/* Unified Alert Banner — ONE system, priority-resolved, tappable actions */}
        {alertState.type !== 'SAFE' && alertState.alert && (() => {
          const isAcked = alertState.alert!.acknowledged === true;
          const isCritical = alertState.type === 'EMERGENCY' || alertState.type === 'ESCALATION';
          // Last seen context from live tracking
          const childId = alertState.alert!.child_id;
          const childLoc = childId ? liveChildren[childId] : null;
          const lastSeenSec = childLoc?.ts ? Math.floor((Date.now() - new Date(childLoc.ts).getTime()) / 1000) : null;
          const lastSeenStr = lastSeenSec !== null
            ? (lastSeenSec < 5 ? 'just now' : lastSeenSec < 60 ? `${lastSeenSec}s ago` : `${Math.floor(lastSeenSec / 60)}m ago`)
            : null;

          // Color: red for active critical, amber for acknowledged, warning for lower priority
          const bannerBg = isAcked
            ? '#D97706' // amber — acknowledged
            : (isCritical || alertState.type === 'VOICE_DISTRESS' || alertState.type === 'HELP')
              ? '#DC2626' // red — active critical
              : colors.warning; // yellow — checkin etc

          return (
            <TouchableOpacity
              style={[uxStyles.sseBanner, { backgroundColor: bannerBg }]}
              onPress={() => handleAlertPress(alertState)}
              activeOpacity={0.8}
              testID="unified-alert-banner"
            >
              <Ionicons
                name={
                  alertState.type === 'EMERGENCY' ? 'warning' :
                  alertState.type === 'ESCALATION' ? 'timer' :
                  alertState.type === 'VOICE_DISTRESS' ? 'mic' :
                  alertState.type === 'HELP' ? 'alert-circle' :
                  'notifications'
                }
                size={20}
                color={colors.white}
              />
              <View style={{ flex: 1 }}>
                <Text style={uxStyles.sseBannerText}>
                  {isAcked ? 'ACK: ' : ''}
                  {alertState.type === 'EMERGENCY' ? 'EMERGENCY: ' :
                   alertState.type === 'ESCALATION' ? 'ESCALATION: ' :
                   alertState.type === 'VOICE_DISTRESS' ? 'VOICE ALERT: ' :
                   alertState.type === 'HELP' ? 'HELP: ' : ''}
                  {alertState.alert!.message}
                </Text>
                <View style={{ flexDirection: 'row', alignItems: 'center', marginTop: 2, gap: 8 }}>
                  {alertState.action && (
                    <Text style={{ color: colors.white + 'CC', fontSize: 11, fontWeight: '600' }}>
                      {alertState.action.label} →
                    </Text>
                  )}
                  {lastSeenStr && (
                    <Text style={{ color: colors.white + 'AA', fontSize: 10 }} testID="alert-last-seen">
                      Last seen: {lastSeenStr}
                    </Text>
                  )}
                </View>
              </View>
              <TouchableOpacity
                onPress={() => removeAlert(alertState.alert!.id)}
                hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}
                testID="unified-banner-dismiss"
              >
                <Ionicons name="close" size={16} color={colors.white + '80'} />
              </TouchableOpacity>
            </TouchableOpacity>
          );
        })()}

        {/* FIX 3 — Stale data warning */}
        {freshness === 'stale' && (
          <View style={uxStyles.staleBanner} testID="stale-data-warning">
            <Ionicons name="warning-outline" size={16} color={colors.warning} />
            <Text style={uxStyles.staleText}>Data may be outdated. Pull to refresh.</Text>
          </View>
        )}

        {/* Tabs */}
        <View style={styles.tabRow}>
          {(['overview', 'alerts', 'map', 'history'] as const).map((t) => (
            <TouchableOpacity key={t} style={[styles.tabBtn, tab === t && styles.tabBtnActive]}
              onPress={() => setTab(t)} testID={`guardian-tab-${t}`}>
              <Text style={[styles.tabLabel, tab === t && styles.tabLabelActive]}>
                {t.charAt(0).toUpperCase() + t.slice(1)}
              </Text>
            </TouchableOpacity>
          ))}
        </View>

        {/* FIX 4 — Loading skeleton */}
        {loading ? (
          <View testID="loading-skeleton">
            {[1, 2, 3].map((k) => (
              <View key={k} style={uxStyles.skeletonCard}>
                <View style={uxStyles.skeletonAvatar} />
                <View style={{ flex: 1, gap: 8 }}>
                  <View style={[uxStyles.skeletonLine, { width: '60%' }]} />
                  <View style={[uxStyles.skeletonLine, { width: '40%' }]} />
                </View>
              </View>
            ))}
          </View>
        ) : fetchError ? (
          /* FIX 4 — Error state with retry */
          <View style={uxStyles.errorCard} testID="fetch-error">
            <Ionicons name="cloud-offline-outline" size={40} color={colors.critical} />
            <Text style={uxStyles.errorTitle}>Failed to load</Text>
            <Text style={uxStyles.errorDesc}>Check your connection and try again</Text>
            <TouchableOpacity style={uxStyles.retryBtn} onPress={() => fetchData(true)} testID="retry-btn">
              <Ionicons name="refresh" size={16} color={colors.white} />
              <Text style={uxStyles.retryText}>Retry</Text>
            </TouchableOpacity>
          </View>
        ) : (
          <>
            {tab === 'overview' && (
              <>
                {sessions.length > 0 && (
                  <>
                    <Text style={styles.sectionTitle}>Active Journeys</Text>
                    {sessions
                      .filter((s: any) => {
                        // FIX 1: Skip if child already shown in Live Tracking map
                        var childId = s.user_id || s.child_id;
                        var childName = s.user_name;
                        var inLive = Object.values(liveChildren).some(function(loc: any) {
                          return loc.child_id === childId || loc.child_name === childName;
                        });
                        return !inLive;
                      })
                      .map((s: any, i: number) => (
                      <View key={i} style={styles.liveSessionCard} testID={`session-card-${i}`}>
                        <View style={styles.liveRow}><View style={styles.liveDot} /><Text style={styles.liveText}>LIVE</Text></View>
                        <Text style={styles.liveSessionName}>{s.user_name || 'Unknown'}</Text>
                        <Text style={styles.liveSessionTime}>Started: {fmtTime(s.started_at)}</Text>
                        {s.zone_name ? <Text style={styles.liveSessionZone}>{s.zone_name}</Text> : null}
                        <TouchableOpacity
                          style={styles.endJourneyBtn}
                          onPress={() => {
                            Alert.alert('End Journey', `End ${s.user_name || 'this'}'s journey?`, [
                              { text: 'Cancel', style: 'cancel' },
                              { text: 'End', style: 'destructive', onPress: async () => {
                                try {
                                  await guardianDashboardService.endSession(s.session_id);
                                  Alert.alert('Done', 'Journey ended.');
                                  fetchData();
                                } catch (e: any) {
                                  Alert.alert('Error', e.response?.data?.detail || 'Failed to end journey');
                                }
                              }},
                            ]);
                          }}
                          testID={`end-journey-btn-${i}`}
                        >
                          <Ionicons name="stop-circle-outline" size={16} color={colors.critical} />
                          <Text style={styles.endJourneyText}>End Journey</Text>
                        </TouchableOpacity>
                      </View>
                    ))}
                  </>
                )}

                {/* Live Tracking */}
                {liveChildren && Object.keys(liveChildren).length > 0 && (
                  <>
                    <Text style={styles.sectionTitle}>Live Tracking</Text>
                    {Object.keys(liveChildren).map(function(cid) {
                      var loc = liveChildren[cid];
                      if (!loc || !loc.lat || !loc.lng) return null;
                      var isMoving = (loc.speed || 0) > 0.3;
                      var riskBg = loc.risk === 'SAFE' ? colors.safe : loc.risk === 'MEDIUM' ? colors.warning : colors.critical;
                      var speedKmh = ((loc.speed || 0) * 3.6).toFixed(1);
                      var trailLen = loc.trail ? loc.trail.length : 0;
                      var secAgo = Math.floor((Date.now() - new Date(loc.ts).getTime()) / 1000);
                      var timeStr = secAgo < 5 ? 'just now' : secAgo < 60 ? secAgo + 's ago' : Math.floor(secAgo / 60) + 'm ago';
                      // Look up the active session_id for this child
                      // so the map can render the authoritative tri-color
                      // historical polyline rather than the in-memory
                      // SSE trail. Falls back silently when no journey
                      // is active.
                      var lovedOne = lovedOnes.find(function(p: any) {
                        return p.user_id === cid || p.id === cid;
                      });
                      var activeSessionId = lovedOne?.active_session?.session_id || null;
                      return (
                        <View key={cid} style={{ marginBottom: spacing.md }} testID="live-tracking-card">
                          <GuardianLiveMap data={loc} sessionId={activeSessionId} />
                        </View>
                      );
                    })}
                  </>
                )}

                <Text style={styles.sectionTitle}>Loved Ones</Text>
                {lovedOnes.length === 0 ? (
                  <View style={styles.emptyCard} testID="empty-loved-ones">
                    <Ionicons name="people-outline" size={40} color={colors.textMuted} />
                    <Text style={styles.emptyText}>No linked loved ones yet</Text>
                    {!showLinkInput ? (
                      <TouchableOpacity style={linkStyles.linkBtn} onPress={() => { setShowLinkInput(true); setLinkError(null); }} testID="link-child-btn">
                        <Ionicons name="link" size={18} color={colors.white} />
                        <Text style={linkStyles.linkBtnText}>Link a Child</Text>
                      </TouchableOpacity>
                    ) : (
                      <View style={linkStyles.linkInputWrap} testID="link-input-section">
                        <TextInput
                          style={linkStyles.linkInput}
                          value={linkCode}
                          onChangeText={(t) => { setLinkCode(t.replace(/\D/g, '').slice(0, 6)); setLinkError(null); }}
                          placeholder="Enter 6-digit code"
                          placeholderTextColor={colors.textMuted}
                          keyboardType="numeric"
                          maxLength={6}
                          testID="link-code-input"
                        />
                        <View style={linkStyles.linkBtnRow}>
                          <TouchableOpacity style={linkStyles.linkCancelBtn} onPress={() => { setShowLinkInput(false); setLinkCode(''); setLinkError(null); }}>
                            <Text style={linkStyles.linkCancelText}>Cancel</Text>
                          </TouchableOpacity>
                          <TouchableOpacity
                            style={[linkStyles.linkSubmitBtn, linkLoading && { opacity: 0.5 }]}
                            onPress={handleLinkChild}
                            disabled={linkLoading}
                            testID="link-submit-btn"
                          >
                            <Text style={linkStyles.linkSubmitText}>{linkLoading ? 'Linking...' : 'Link'}</Text>
                          </TouchableOpacity>
                        </View>
                        {linkError && <Text style={linkStyles.linkError} testID="link-error-text">{linkError}</Text>}
                      </View>
                    )}
                  </View>
                ) : (
                  <>
                    {/* Secondary "Link a Child" when list is populated */}
                    {!showLinkInput ? (
                      <TouchableOpacity
                        style={linkStyles.linkSecondaryBtn}
                        onPress={() => { setShowLinkInput(true); setLinkError(null); }}
                        testID="link-child-secondary-btn"
                      >
                        <Ionicons name="add-circle-outline" size={16} color={colors.primary} />
                        <Text style={linkStyles.linkSecondaryText}>Link a Child</Text>
                      </TouchableOpacity>
                    ) : (
                      <View style={[linkStyles.linkInputWrap, { marginBottom: spacing.md }]} testID="link-input-section-secondary">
                        <TextInput
                          style={linkStyles.linkInput}
                          value={linkCode}
                          onChangeText={(t) => { setLinkCode(t.replace(/\D/g, '').slice(0, 6)); setLinkError(null); }}
                          placeholder="Enter 6-digit code"
                          placeholderTextColor={colors.textMuted}
                          keyboardType="numeric"
                          maxLength={6}
                          testID="link-code-input-secondary"
                        />
                        <View style={linkStyles.linkBtnRow}>
                          <TouchableOpacity style={linkStyles.linkCancelBtn} onPress={() => { setShowLinkInput(false); setLinkCode(''); setLinkError(null); }}>
                            <Text style={linkStyles.linkCancelText}>Cancel</Text>
                          </TouchableOpacity>
                          <TouchableOpacity
                            style={[linkStyles.linkSubmitBtn, linkLoading && { opacity: 0.5 }]}
                            onPress={handleLinkChild}
                            disabled={linkLoading}
                            testID="link-submit-btn-secondary"
                          >
                            <Text style={linkStyles.linkSubmitText}>{linkLoading ? 'Linking...' : 'Link'}</Text>
                          </TouchableOpacity>
                        </View>
                        {linkError && <Text style={linkStyles.linkError}>{linkError}</Text>}
                      </View>
                    )}

                    {lovedOnes.map((p: any, i: number) => {
                      const resolved = resolveChildStatus(p, checkInStatuses[p.id], sessions, apiAlerts);
                      // Use server status if available, otherwise use client resolver
                      const displayStatus = p.serverStatus || resolved.status.toUpperCase();
                      const statusConfig = getStatusBadgeConfig(displayStatus);

                      // FIX 2 — PANIC MODE for emergency / help
                      if (resolved.status === 'emergency' || resolved.status === 'help') {
                        return (
                          <View key={i} style={uxStyles.panicCard} testID={`loved-one-panic-${i}`}>
                            <View style={uxStyles.panicHeader}>
                              <Ionicons name={resolved.icon} size={22} color={colors.white} />
                              <Text style={uxStyles.panicLabel}>{resolved.label}</Text>
                            </View>
                            <Text style={uxStyles.panicName}>{p.name}</Text>
                            {p.location && (
                              <View style={linkStyles.locRow}>
                                <View style={[linkStyles.locDot, { backgroundColor: colors.critical }]} />
                                <Text style={[linkStyles.locText, { color: colors.white + 'CC' }]}>Emergency location</Text>
                              </View>
                            )}
                            {resolved.since && (
                              <Text style={uxStyles.panicTime}>Since {fmtTime(resolved.since)}</Text>
                            )}
                            <TouchableOpacity
                              style={uxStyles.callNowBtn}
                              onPress={() => { Linking.openURL(`tel:${p.phone || '112'}`); }}
                              testID={`call-now-btn-${i}`}
                            >
                              <Ionicons name="call" size={20} color={colors.white} />
                              <Text style={uxStyles.callNowText}>CALL NOW</Text>
                            </TouchableOpacity>
                            <View style={uxStyles.panicSecondary}>
                              <TouchableOpacity
                                style={uxStyles.secondaryBtn}
                                testID={`view-live-btn-${i}`}
                                onPress={() => setTab('map')}
                              >
                                <Ionicons name="location" size={14} color={colors.critical} />
                                <Text style={uxStyles.secondaryBtnText}>View Live</Text>
                              </TouchableOpacity>
                              <TouchableOpacity
                                style={uxStyles.secondaryBtn}
                                onPress={() => handleCheckIn(p.id, p.name)}
                                testID={`send-checkin-btn-${i}`}
                              >
                                <Ionicons name="chatbubble-ellipses" size={14} color={colors.critical} />
                                <Text style={uxStyles.secondaryBtnText}>Send Check-In</Text>
                              </TouchableOpacity>
                            </View>
                          </View>
                        );
                      }

                      // Normal card with enhanced location + status
                      return (
                        <View key={i} style={styles.personCard} testID={`loved-one-${i}`}>
                          <View style={[
                            styles.personAvatar,
                            resolved.status === 'live_journey' && { backgroundColor: colors.primary + '30' },
                          ]}>
                            <Ionicons name="person" size={24} color={resolved.color} />
                          </View>
                          <View style={styles.personInfo}>
                            <Text style={styles.personName}>{p.name || 'User'}</Text>
                            {/* Status badge */}
                            <View style={[linkStyles.statusPill, { backgroundColor: statusConfig.bg }]} testID={`status-badge-${i}`}>
                              <View style={[linkStyles.statusDot, { backgroundColor: statusConfig.color }]} />
                              <Text style={[linkStyles.statusText, { color: statusConfig.color }]}>{statusConfig.label}</Text>
                            </View>
                            {/* Location display */}
                            <LovedOneLocation locationType={p.locationType} lastUpdated={p.lastUpdated} location={p.location} testID={`location-${i}`} />
                          </View>
                          <TouchableOpacity
                            style={[styles.checkBtn, checkingIn === p.id && { opacity: 0.5 }]}
                            onPress={() => handleCheckIn(p.id, p.name)}
                            disabled={checkingIn === p.id}
                            testID={`check-btn-${i}`}
                          >
                            <Text style={styles.checkBtnText}>{checkingIn === p.id ? '...' : 'Check In'}</Text>
                          </TouchableOpacity>
                        </View>
                      );
                    })}

                    {/* HC-01 Day 4 — Dependents vitals strip. Renders one
                        card per loved-one with their latest wearable
                        readings. 403/no-data states render as a quiet
                        "No wearable data yet" inside each card. */}
                    {lovedOnes.length > 0 && (
                      <View testID="dependents-vitals-section" style={{ marginTop: spacing.lg }}>
                        <Text style={styles.sectionTitle}>Wearable Vitals</Text>
                        {lovedOnes.map((p: any, i: number) => (
                          <DependentVitalsCard
                            key={`vitals-${p.id || i}`}
                            dependentId={p.id}
                            dependentName={p.name}
                          />
                        ))}
                      </View>
                    )}
                  </>
                )}
              </>
            )}

            {tab === 'alerts' && (
              <>
                <Text style={styles.sectionTitle}>Recent Alerts</Text>
                {apiAlerts.length === 0 ? (
                  <View style={styles.emptyCard}>
                    <Ionicons name="shield-checkmark" size={40} color={colors.safe} />
                    <Text style={styles.emptyText}>No alerts</Text>
                  </View>
                ) : (
                  apiAlerts.map((a: any, i: number) => (
                    <View key={i} style={styles.alertCard} testID={`alert-item-${i}`}>
                      <View style={[styles.alertDot, { backgroundColor: riskColor(a.severity || 'moderate') }]} />
                      <View style={styles.alertInfo}>
                        <Text style={styles.alertType}>{a.alert_type || a.type || 'Alert'}{a.user_name ? ` — ${a.user_name}` : ''}</Text>
                        <Text style={styles.alertMsg} numberOfLines={1}>{a.message || ''}</Text>
                        <Text style={styles.alertTime}>{fmtTime(a.created_at || a.timestamp)}</Text>
                      </View>
                    </View>
                  ))
                )}
              </>
            )}

            {tab === 'map' && (
              <View style={{ height: 500, borderRadius: 12, overflow: 'hidden', marginBottom: 16 }}>
                <RiskOverlayMap />
              </View>
            )}

            {tab === 'history' && (
              <>
                <Text style={styles.sectionTitle}>Journey History</Text>
                <HistoryList />
              </>
            )}
          </>
        )}
      </ScrollView>
    </View>
  );
}

function HistoryList() {
  const [history, setHistory] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    guardianDashboardService.getHistory()
      .then((r) => setHistory(Array.isArray(r.data) ? r.data : r.data?.sessions || []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <View style={styles.loadingWrap}><Text style={styles.loadingText}>Loading...</Text></View>;
  if (history.length === 0) return (
    <View style={styles.emptyCard}><Ionicons name="time-outline" size={40} color={colors.textMuted} /><Text style={styles.emptyText}>No journey history</Text></View>
  );

  return (
    <>
      {history.map((h: any, i: number) => (
        <View key={i} style={styles.historyCard} testID={`history-item-${i}`}>
          <Ionicons name="navigate-circle" size={20} color={colors.primary} />
          <View style={{ flex: 1 }}>
            <Text style={styles.historyId}>{h.session_id?.slice(0, 12)}...</Text>
            <Text style={styles.historyTime}>
              {toIST(h.start_time)} — {h.end_time ? toIST(h.end_time) : 'ongoing'}
            </Text>
          </View>
          <Text style={{ fontSize: fontSize.xs, fontWeight: '700', color: h.status === 'completed' ? colors.safe : colors.warning, textTransform: 'capitalize' }}>{h.status || 'unknown'}</Text>
        </View>
      ))}
    </>
  );
}

// =====================================================================
// WOMEN DASHBOARD — full features (score, journey, alerts, share)
// =====================================================================

function WomenDashboard() {
  const router = useRouter();
  const { user } = useAuthStore();
  const { isActive, isTriggering } = useEmergencyStore();
  const [refreshing, setRefreshing] = useState(false);
  const [safetyScore, setSafetyScore] = useState<any>(null);
  const [activeSession, setActiveSession] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    try {
      const [scoreRes, sesRes] = await Promise.all([
        safetyScoreService.getLocationScore(12.9716, 77.5946).catch(() => ({ data: null })),
        guardianService.getSession('current').catch(() => ({ data: {} })),
      ]);
      setSafetyScore(scoreRes.data);
      const sessions = sesRes.data?.sessions || [];
      setActiveSession(sessions.find((s: any) => s.status === 'active') || null);
    } catch {}
    setLoading(false);
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);
  const onRefresh = async () => { setRefreshing(true); await fetchData(); setRefreshing(false); };

  const score = safetyScore?.score ?? 0;

  return (
    <View style={{ flex: 1 }} testID="women-dashboard">
      <ScrollView style={styles.scroll} contentContainerStyle={[styles.content, { paddingBottom: 20 }]}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.primary} />}>

        <EmergencyBanner />

        {/* HC-01 Day 3 — Wearable connect onboard + live vitals (women dashboard). */}
        <WearableConnectCard />
        <VitalsStrip />

        {/* Safety Score */}
        <TouchableOpacity style={styles.scoreCard} onPress={() => router.push('/(tabs)/safety-score')} testID="home-score-card">
          <View style={styles.scoreRing}>
            <View style={[styles.scoreCircle, { borderColor: scoreColor(score) }]}>
              <Text style={[styles.scoreNum, { color: scoreColor(score) }]}>{loading ? '--' : score.toFixed(1)}</Text>
              <Text style={styles.scoreOf}>/10</Text>
            </View>
          </View>
          <View style={styles.scoreMeta}>
            <Text style={[styles.scoreLabel, { color: scoreColor(score) }]}>{loading ? 'Loading...' : scoreLabel(score)}</Text>
            <Text style={styles.scoreDesc}>Your area safety score</Text>
          </View>
          <Ionicons name="chevron-forward" size={20} color={colors.textMuted} />
        </TouchableOpacity>

        {/* Quick Actions */}
        <Text style={styles.sectionTitle}>Quick Actions</Text>
        <View style={styles.actionsGrid}>
          <ActionCard icon="navigate-circle" label="Start Journey" color={colors.primary}
            onPress={() => router.push('/(tabs)/journey')} testID="action-start-journey" />
          <ActionCard icon="map" label="Safe Routes" color={colors.verySafe}
            onPress={() => router.push('/(tabs)/journey')} testID="action-safe-routes" />
          <ActionCard icon="warning" label="Alerts" color={colors.warning}
            onPress={() => router.push('/(tabs)/alerts')} testID="action-alerts" />
          <ActionCard icon="share-social" label="Share Safety" color={colors.accent}
            onPress={() => router.push('/(tabs)/guardian')} testID="action-share-safety" />
        </View>

        {activeSession && (
          <View style={styles.sessionCard} testID="active-session-card">
            <View style={styles.sessionDot} />
            <View style={styles.sessionInfo}>
              <Text style={styles.sessionTitle}>Active Journey</Text>
              <Text style={styles.sessionSub}>Session: {activeSession.session_id?.slice(0, 8)}...</Text>
            </View>
            <TouchableOpacity style={styles.sessionBtn} onPress={() => router.push('/(tabs)/journey')}>
              <Text style={styles.sessionBtnText}>View</Text>
            </TouchableOpacity>
          </View>
        )}

        <SOSButton />
      </ScrollView>
    </View>
  );
}

// =====================================================================
// LOVED ONE HELPERS — status badge config, location display, relative time
// =====================================================================

function relativeTime(isoStr: string | null): string {
  if (!isoStr) return '';
  const diff = Date.now() - new Date(isoStr).getTime();
  const sec = Math.floor(diff / 1000);
  if (sec < 60) return 'just now';
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const days = Math.floor(hr / 24);
  return `${days}d ago`;
}

function getStatusBadgeConfig(status: string): { label: string; color: string; bg: string } {
  const s = (status || '').toUpperCase();
  if (s === 'EMERGENCY') return { label: 'EMERGENCY', color: colors.critical, bg: colors.critical + '20' };
  if (s === 'VOICE_DISTRESS') return { label: 'Voice Distress!', color: colors.critical, bg: colors.critical + '20' };
  if (s === 'LIVE_JOURNEY') return { label: 'Live Journey', color: '#3B82F6', bg: '#3B82F620' };
  if (s === 'CHECK_IN_PENDING') return { label: 'Check-in Pending', color: '#F59E0B', bg: '#F59E0B20' };
  if (s === 'HELP') return { label: 'Needs Help', color: colors.critical, bg: colors.critical + '20' };
  return { label: 'Safe', color: colors.safe, bg: colors.safe + '20' };
}

function LovedOneLocation({ locationType, lastUpdated, location, testID }: { locationType: string | null; lastUpdated: string | null; location: any; testID?: string }) {
  if (!location && !locationType) {
    return (
      <View style={linkStyles.locRow} testID={testID}>
        <Text style={[linkStyles.locText, { color: colors.textMuted }]}>Location unavailable</Text>
      </View>
    );
  }

  let dotColor = colors.textMuted;
  let label = 'Unknown';

  if (locationType === 'live') {
    dotColor = colors.safe;
    label = 'Live';
  } else if (locationType === 'emergency') {
    dotColor = colors.critical;
    label = 'Emergency location';
  } else if (locationType === 'recent') {
    dotColor = '#F59E0B';
    label = `Last seen · ${relativeTime(lastUpdated)}`;
  } else if (locationType === 'historical') {
    dotColor = '#9CA3AF';
    label = `Last known · ${relativeTime(lastUpdated)}`;
  }

  return (
    <View style={linkStyles.locRow} testID={testID}>
      <View style={[linkStyles.locDot, { backgroundColor: dotColor }]} />
      <Text style={linkStyles.locText}>{label}</Text>
    </View>
  );
}

// =====================================================================
// STYLES
// =====================================================================

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.bg },
  scroll: { flex: 1 },
  content: { padding: spacing.xl, paddingBottom: spacing['5xl'] },

  // Header
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: spacing.lg,
    paddingVertical: 12,
    backgroundColor: colors.bg,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  fixedHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 12,
    backgroundColor: colors.bgCard,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  logoutBtn: { marginLeft: 8 },
  greeting: { fontSize: fontSize.xl, fontWeight: '800', color: colors.textPrimary },
  profileBadge: { flexDirection: 'row', alignItems: 'center', gap: spacing.xs, backgroundColor: colors.bgCard, alignSelf: 'flex-start', paddingHorizontal: spacing.md, paddingVertical: spacing.xs, borderRadius: radius.full, borderWidth: 1, borderColor: colors.border, marginTop: spacing.sm },
  profileText: { fontSize: fontSize.xs, fontWeight: '600', color: colors.primary },

  // Emergency
  emergencyBanner: { flexDirection: 'row', alignItems: 'center', backgroundColor: colors.critical, borderRadius: radius.xl, padding: spacing.lg, marginBottom: spacing.lg, overflow: 'hidden' },
  emergencyPulse: { ...StyleSheet.absoluteFillObject, backgroundColor: colors.critical },
  emergencyInfo: { flex: 1 },
  emergencyTitle: { fontSize: fontSize.lg, fontWeight: '900', color: colors.white, letterSpacing: 2 },
  emergencySub: { fontSize: fontSize.sm, color: colors.white + '99' },
  emergencyAction: { fontSize: fontSize.xs, color: colors.white + '80', marginTop: 4 },
  triggeringBanner: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, backgroundColor: colors.warning + '20', borderRadius: radius.lg, padding: spacing.md, marginBottom: spacing.lg, borderWidth: 1, borderColor: colors.warning + '40' },
  triggeringText: { fontSize: fontSize.sm, fontWeight: '600', color: colors.warning },

  // Score card
  scoreCard: { flexDirection: 'row', alignItems: 'center', backgroundColor: colors.bgCard, borderRadius: radius.xl, padding: spacing.xl, borderWidth: 1, borderColor: colors.border, ...shadows.lg, marginBottom: spacing.xl },
  scoreRing: { marginRight: spacing.lg },
  scoreCircle: { width: 70, height: 70, borderRadius: 35, borderWidth: 4, justifyContent: 'center', alignItems: 'center', backgroundColor: colors.bgElevated },
  scoreNum: { fontSize: fontSize['2xl'], fontWeight: '900' },
  scoreOf: { fontSize: fontSize.xs, color: colors.textMuted, marginTop: -2 },
  scoreMeta: { flex: 1 },
  scoreLabel: { fontSize: fontSize.lg, fontWeight: '800' },
  scoreDesc: { fontSize: fontSize.sm, color: colors.textSecondary, marginTop: 2 },

  // Actions grid
  sectionTitle: { fontSize: fontSize.lg, fontWeight: '700', color: colors.textPrimary, marginBottom: spacing.md, marginTop: spacing.sm },
  actionsGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.md, marginBottom: spacing.xl },
  actionCard: { width: '47%', backgroundColor: colors.bgCard, borderRadius: radius.xl, padding: spacing.lg, alignItems: 'center', gap: spacing.sm, borderWidth: 1, borderColor: colors.border, ...shadows.sm },
  actionIcon: { width: 48, height: 48, borderRadius: 24, justifyContent: 'center', alignItems: 'center' },
  actionLabel: { fontSize: fontSize.sm, fontWeight: '600', color: colors.textPrimary, textAlign: 'center' },

  // Session card
  sessionCard: { flexDirection: 'row', alignItems: 'center', backgroundColor: colors.bgCard, borderRadius: radius.xl, padding: spacing.lg, borderWidth: 1, borderColor: colors.safe + '30', marginBottom: spacing.xl },
  sessionDot: { width: 10, height: 10, borderRadius: 5, backgroundColor: colors.safe, marginRight: spacing.md },
  sessionInfo: { flex: 1 },
  sessionTitle: { fontSize: fontSize.md, fontWeight: '700', color: colors.textPrimary },
  sessionSub: { fontSize: fontSize.xs, color: colors.textMuted },
  sessionBtn: { backgroundColor: colors.primary + '20', paddingHorizontal: spacing.lg, paddingVertical: spacing.sm, borderRadius: radius.full },
  sessionBtnText: { fontSize: fontSize.sm, fontWeight: '600', color: colors.primary },

  // SOS Button
  sosBtn: { flexDirection: 'column', alignItems: 'center', justifyContent: 'center', backgroundColor: colors.critical + '10', borderRadius: radius.xl, padding: spacing.xl, borderWidth: 2, borderColor: colors.critical + '40', gap: spacing.xs },
  sosBtnActive: { backgroundColor: colors.critical, borderColor: colors.critical },
  sosText: { fontSize: fontSize.md, fontWeight: '800', color: colors.critical },
  sosTextActive: { color: colors.white },
  sosHint: { fontSize: fontSize.xs, color: colors.textMuted, textAlign: 'center' },
  sosHintActive: { color: colors.white + '80' },

  // Modals
  modalOverlay: { flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: 'rgba(0,0,0,0.7)', padding: spacing.xl },
  modalCard: { backgroundColor: colors.bgCard, borderRadius: radius.xl, padding: spacing['2xl'], width: '100%', alignItems: 'center', gap: spacing.md, borderWidth: 1, borderColor: colors.border },
  modalTitle: { fontSize: fontSize.xl, fontWeight: '800', color: colors.textPrimary },
  modalDesc: { fontSize: fontSize.sm, color: colors.textSecondary, textAlign: 'center' },
  modalLabel: { fontSize: fontSize.sm, fontWeight: '600', color: colors.textMuted, alignSelf: 'flex-start' },
  pinInput: { width: '100%', backgroundColor: colors.bgElevated, borderRadius: radius.lg, padding: spacing.md, fontSize: fontSize.xl, fontWeight: '700', color: colors.textPrimary, textAlign: 'center', letterSpacing: 12, borderWidth: 1, borderColor: colors.border },
  modalBtns: { flexDirection: 'row', gap: spacing.md, width: '100%', marginTop: spacing.sm },
  modalCancelBtn: { flex: 1, paddingVertical: spacing.md, alignItems: 'center', borderRadius: radius.lg, backgroundColor: colors.bgElevated, borderWidth: 1, borderColor: colors.border },
  modalCancelText: { fontSize: fontSize.md, fontWeight: '600', color: colors.textMuted },
  modalConfirmBtn: { flex: 1, paddingVertical: spacing.md, alignItems: 'center', borderRadius: radius.lg, backgroundColor: colors.critical },
  modalConfirmText: { fontSize: fontSize.md, fontWeight: '800', color: colors.white },
  modalSafeBtn: { flex: 1, paddingVertical: spacing.md, alignItems: 'center', borderRadius: radius.lg, backgroundColor: colors.safe },

  // Guardian tabs
  tabRow: { flexDirection: 'row', gap: spacing.xs, marginBottom: spacing.xl },
  tabBtn: { flex: 1, paddingVertical: spacing.sm, borderRadius: radius.lg, backgroundColor: colors.bgCard, alignItems: 'center', borderWidth: 1, borderColor: colors.border },
  tabBtnActive: { backgroundColor: colors.primary + '20', borderColor: colors.primary },
  tabLabel: { fontSize: fontSize.xs, fontWeight: '600', color: colors.textMuted },
  tabLabelActive: { color: colors.primary },
  loadingWrap: { paddingVertical: spacing['4xl'], alignItems: 'center' },
  loadingText: { color: colors.textMuted },

  // Guardian cards
  liveSessionCard: { backgroundColor: colors.bgCard, borderRadius: radius.lg, padding: spacing.lg, borderWidth: 1, borderColor: colors.safe + '30', marginBottom: spacing.md },
  liveRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, marginBottom: spacing.sm },
  liveDot: { width: 8, height: 8, borderRadius: 4, backgroundColor: colors.safe },
  liveText: { fontSize: fontSize.xs, fontWeight: '800', color: colors.safe, letterSpacing: 2 },
  liveSessionName: { fontSize: fontSize.md, fontWeight: '700', color: colors.textPrimary },
  liveSessionTime: { fontSize: fontSize.xs, color: colors.textMuted, marginTop: 2 },
  liveSessionZone: { fontSize: fontSize.xs, color: colors.textSecondary, marginTop: 2 },
  endJourneyBtn: { flexDirection: 'row', alignItems: 'center', gap: spacing.xs, backgroundColor: colors.critical + '10', paddingHorizontal: spacing.md, paddingVertical: spacing.sm, borderRadius: radius.full, borderWidth: 1, borderColor: colors.critical + '30', marginTop: spacing.sm, alignSelf: 'flex-start' },
  endJourneyText: { fontSize: fontSize.xs, fontWeight: '700', color: colors.critical },
  personCard: { flexDirection: 'row', alignItems: 'center', backgroundColor: colors.bgCard, borderRadius: radius.lg, padding: spacing.lg, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.md },
  personAvatar: { width: 44, height: 44, borderRadius: 22, backgroundColor: colors.primary + '20', justifyContent: 'center', alignItems: 'center', marginRight: spacing.md },
  personInfo: { flex: 1 },
  personName: { fontSize: fontSize.md, fontWeight: '700', color: colors.textPrimary },
  personStatus: { fontSize: fontSize.sm, color: colors.safe, marginTop: 2 },
  personRelation: { fontSize: fontSize.xs, color: colors.textMuted, textTransform: 'capitalize', marginTop: 1 },
  checkBtn: { backgroundColor: colors.primary + '20', paddingHorizontal: spacing.lg, paddingVertical: spacing.sm, borderRadius: radius.full },
  checkBtnText: { fontSize: fontSize.sm, fontWeight: '600', color: colors.primary },
  emptyCard: { backgroundColor: colors.bgCard, borderRadius: radius.xl, padding: spacing['3xl'], alignItems: 'center', gap: spacing.sm, borderWidth: 1, borderColor: colors.border },
  emptyText: { fontSize: fontSize.md, color: colors.textMuted },
  alertCard: { flexDirection: 'row', alignItems: 'center', backgroundColor: colors.bgCard, borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.sm },
  alertDot: { width: 8, height: 8, borderRadius: 4, marginRight: spacing.md },
  alertInfo: { flex: 1 },
  alertType: { fontSize: fontSize.sm, fontWeight: '600', color: colors.textPrimary, textTransform: 'capitalize' },
  alertMsg: { fontSize: fontSize.xs, color: colors.textSecondary, marginTop: 1 },
  alertTime: { fontSize: fontSize.xs, color: colors.textMuted, marginTop: 1 },
  historyCard: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, backgroundColor: colors.bgCard, borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.sm },
  historyId: { fontSize: fontSize.sm, fontWeight: '600', color: colors.textPrimary },
  historyTime: { fontSize: fontSize.xs, color: colors.textMuted },

  // Check-In Banner (child side)
  checkInBanner: { backgroundColor: colors.warning + '15', borderRadius: radius.xl, padding: spacing.lg, borderWidth: 1, borderColor: colors.warning + '40', marginBottom: spacing.lg },
  checkInHeader: { flexDirection: 'row', alignItems: 'center', marginBottom: spacing.md },
  checkInTitle: { fontSize: fontSize.md, fontWeight: '800', color: colors.warning },
  checkInDesc: { fontSize: fontSize.sm, color: colors.textSecondary, marginTop: 2 },
  checkInActions: { flexDirection: 'row', gap: spacing.md },
  checkInSafeBtn: { flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: spacing.xs, backgroundColor: colors.safe, paddingVertical: spacing.md, borderRadius: radius.lg },
  checkInSafeText: { fontSize: fontSize.sm, fontWeight: '800', color: colors.white },
  checkInHelpBtn: { flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: spacing.xs, backgroundColor: colors.critical, paddingVertical: spacing.md, borderRadius: radius.lg },
  checkInHelpText: { fontSize: fontSize.sm, fontWeight: '800', color: colors.white },

  // Check-In Status badges (guardian side)
  checkInStatusPending: { flexDirection: 'row', alignItems: 'center', gap: 4, marginTop: 3 },
  checkInStatusPendingText: { fontSize: fontSize.xs, color: colors.warning, fontWeight: '600' },
  checkInStatusSafe: { flexDirection: 'row', alignItems: 'center', gap: 4, marginTop: 3 },
  checkInStatusSafeText: { fontSize: fontSize.xs, color: colors.safe, fontWeight: '600' },
  checkInStatusHelp: { flexDirection: 'row', alignItems: 'center', gap: 4, marginTop: 3 },
  checkInStatusHelpText: { fontSize: fontSize.xs, color: colors.critical, fontWeight: '600' },
  checkInStatusExpired: { flexDirection: 'row', alignItems: 'center', gap: 4, marginTop: 3 },
});

// ── UX Fix Styles ──
const uxStyles = StyleSheet.create({
  // FIX 3 — Freshness indicator
  freshnessRow: { flexDirection: 'row', alignItems: 'center', gap: 6, marginBottom: spacing.sm },
  freshDot: { width: 8, height: 8, borderRadius: 4, backgroundColor: colors.textMuted + '40' },
  freshDotLive: { backgroundColor: colors.safe },
  freshDotStale: { backgroundColor: colors.warning },
  freshDotOffline: { backgroundColor: colors.critical },
  freshLabel: { fontSize: fontSize.xs, fontWeight: '700', color: colors.textMuted, letterSpacing: 1 },
  freshTimestamp: { fontSize: fontSize.xs, color: colors.textMuted, marginLeft: 4 },

  // FIX 3 — Stale data warning
  staleBanner: { flexDirection: 'row', alignItems: 'center', gap: 8, backgroundColor: colors.warning + '18', borderWidth: 1, borderColor: colors.warning + '40', borderRadius: radius.md, padding: spacing.sm, marginBottom: spacing.md },
  staleText: { fontSize: fontSize.xs, color: colors.warning },

  // FIX 4 — Offline banner
  offlineBanner: { flexDirection: 'row', alignItems: 'center', gap: 8, backgroundColor: colors.critical + '18', borderWidth: 1, borderColor: colors.critical + '30', borderRadius: radius.md, padding: spacing.sm, marginBottom: spacing.md },
  offlineText: { fontSize: fontSize.xs, color: colors.warning },

  // SSE banner
  sseBanner: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, borderRadius: radius.lg, padding: spacing.md, marginBottom: spacing.md },
  sseBannerHelp: { backgroundColor: colors.critical },
  sseBannerSafe: { backgroundColor: colors.safe },
  sseBannerText: { flex: 1, fontSize: fontSize.sm, fontWeight: '700', color: colors.white },

  // FIX 1 — Status badge (unified)
  statusBadge: { flexDirection: 'row', alignItems: 'center', gap: 4, marginTop: 2 },
  statusBadgeText: { fontSize: fontSize.xs, fontWeight: '600' },

  // FIX 2 — Panic card
  panicCard: { backgroundColor: colors.critical + '18', borderWidth: 2, borderColor: colors.critical, borderRadius: radius.lg, padding: spacing.lg, marginBottom: spacing.md },
  panicHeader: { flexDirection: 'row', alignItems: 'center', gap: 8, backgroundColor: colors.critical, borderRadius: radius.md, paddingVertical: 6, paddingHorizontal: 12, alignSelf: 'flex-start', marginBottom: spacing.sm },
  panicLabel: { fontSize: fontSize.sm, fontWeight: '800', color: colors.white, letterSpacing: 1 },
  panicName: { fontSize: fontSize.lg, fontWeight: '800', color: colors.white, marginBottom: 4 },
  panicTime: { fontSize: fontSize.xs, color: colors.white + 'AA', marginBottom: spacing.md },
  callNowBtn: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 10, backgroundColor: colors.critical, borderRadius: radius.lg, paddingVertical: 16, marginBottom: spacing.sm },
  callNowText: { fontSize: fontSize.md, fontWeight: '900', color: colors.white, letterSpacing: 2 },
  panicSecondary: { flexDirection: 'row', gap: spacing.sm },
  secondaryBtn: { flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6, backgroundColor: colors.critical + '25', borderRadius: radius.md, paddingVertical: 10 },
  secondaryBtnText: { fontSize: fontSize.xs, fontWeight: '600', color: colors.critical },

  // FIX 4 — Skeleton
  skeletonCard: { flexDirection: 'row', alignItems: 'center', gap: 12, backgroundColor: colors.bgCard, borderRadius: radius.lg, padding: spacing.md, marginBottom: spacing.sm },
  skeletonAvatar: { width: 44, height: 44, borderRadius: 22, backgroundColor: colors.border },
  skeletonLine: { height: 12, borderRadius: 6, backgroundColor: colors.border },

  // FIX 4 — Error state
  errorCard: { alignItems: 'center', gap: spacing.sm, backgroundColor: colors.bgCard, borderRadius: radius.lg, padding: spacing.xl, marginTop: spacing.lg },
  errorTitle: { fontSize: fontSize.md, fontWeight: '700', color: colors.textPrimary },
  errorDesc: { fontSize: fontSize.sm, color: colors.textMuted, textAlign: 'center' },
  retryBtn: { flexDirection: 'row', alignItems: 'center', gap: 6, backgroundColor: colors.primary, borderRadius: radius.md, paddingVertical: 10, paddingHorizontal: 20, marginTop: spacing.sm },
  retryText: { fontSize: fontSize.sm, fontWeight: '700', color: colors.white },
});

// ── Link & Loved One Card Styles ──
const linkStyles = StyleSheet.create({
  // Child: code generation card
  codeCard: { backgroundColor: colors.bgCard, borderRadius: radius.xl, padding: spacing.xl, alignItems: 'center', gap: spacing.sm, borderWidth: 1, borderColor: '#8B5CF640', marginBottom: spacing.xl },
  codeLabel: { fontSize: fontSize.sm, fontWeight: '600', color: colors.textMuted, letterSpacing: 1 },
  codeDigits: { fontSize: 48, fontWeight: '900', color: colors.textPrimary, letterSpacing: 12 },
  codeExpiry: { fontSize: fontSize.sm, fontWeight: '700', color: '#F59E0B' },
  codeInstruction: { fontSize: fontSize.sm, color: colors.textSecondary },
  codeLoading: { fontSize: fontSize.md, color: colors.textMuted },
  codeError: { fontSize: fontSize.sm, color: colors.critical, textAlign: 'center' },
  codeExpired: { fontSize: fontSize.md, color: colors.textMuted, marginBottom: spacing.xs },
  retryBtn: { backgroundColor: '#8B5CF6', paddingHorizontal: spacing.xl, paddingVertical: spacing.md, borderRadius: radius.lg },
  retryText: { fontSize: fontSize.sm, fontWeight: '700', color: colors.white },

  // Guardian: link child button + input
  linkBtn: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, backgroundColor: colors.primary, paddingHorizontal: spacing.xl, paddingVertical: spacing.md, borderRadius: radius.lg, marginTop: spacing.md },
  linkBtnText: { fontSize: fontSize.md, fontWeight: '700', color: colors.white },
  linkSecondaryBtn: { flexDirection: 'row', alignItems: 'center', gap: spacing.xs, alignSelf: 'flex-end', paddingVertical: spacing.xs, marginBottom: spacing.sm },
  linkSecondaryText: { fontSize: fontSize.sm, fontWeight: '600', color: colors.primary },
  linkInputWrap: { backgroundColor: colors.bgCard, borderRadius: radius.lg, padding: spacing.lg, borderWidth: 1, borderColor: colors.border, gap: spacing.sm, marginTop: spacing.sm },
  linkInput: { backgroundColor: colors.bgElevated, borderRadius: radius.lg, paddingHorizontal: spacing.lg, paddingVertical: spacing.md, fontSize: 24, fontWeight: '700', color: colors.textPrimary, textAlign: 'center', letterSpacing: 8, borderWidth: 1, borderColor: colors.border },
  linkBtnRow: { flexDirection: 'row', gap: spacing.md },
  linkCancelBtn: { flex: 1, paddingVertical: spacing.md, alignItems: 'center', borderRadius: radius.lg, backgroundColor: colors.bgElevated, borderWidth: 1, borderColor: colors.border },
  linkCancelText: { fontSize: fontSize.md, fontWeight: '600', color: colors.textMuted },
  linkSubmitBtn: { flex: 1, paddingVertical: spacing.md, alignItems: 'center', borderRadius: radius.lg, backgroundColor: colors.primary },
  linkSubmitText: { fontSize: fontSize.md, fontWeight: '700', color: colors.white },
  linkError: { fontSize: fontSize.sm, color: colors.critical, textAlign: 'center' },

  // Loved one card: status pill + location row
  statusPill: { flexDirection: 'row', alignItems: 'center', gap: 4, paddingHorizontal: 8, paddingVertical: 2, borderRadius: 20, alignSelf: 'flex-start', marginTop: 3 },
  statusDot: { width: 6, height: 6, borderRadius: 3 },
  statusText: { fontSize: fontSize.xs, fontWeight: '700' },
  locRow: { flexDirection: 'row', alignItems: 'center', gap: 5, marginTop: 3 },
  locDot: { width: 7, height: 7, borderRadius: 3.5 },
  locText: { fontSize: fontSize.xs, color: colors.textSecondary },
});
