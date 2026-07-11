import { useRef, useState } from 'react';
import { KeyboardAvoidingView, Platform, ScrollView, StyleSheet, Text, TextInput, TouchableOpacity, View } from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useAuthStore } from '@/stores/authStore';
import { NischintLogo } from '@/components/NischintLogo';
import { colors } from '@/theme';

const TOTAL_STEPS = 6;

export default function ProfileSelectScreen() {
  const { startLocalPreview } = useAuthStore();
  const params = useLocalSearchParams<{ phone?: string }>();
  const router = useRouter();
  const [step, setStep] = useState(2);
  const [email, setEmail] = useState('');
  const [firstName, setFirstName] = useState('');
  const [lastName, setLastName] = useState('');
  const [joinMode, setJoinMode] = useState<'create' | 'join' | null>(null);
  const [joinMethod, setJoinMethod] = useState<'qr' | 'code' | null>(null);
  const [inviteCode, setInviteCode] = useState('');
  const inviteInputRef = useRef<TextInput>(null);
  const [profileRole, setProfileRole] = useState<'child' | 'woman' | 'senior' | 'family' | null>(null);
  const [privacy, setPrivacy] = useState({
    ai: false,
    location: false,
    microphone: false,
    wearable: false,
    background: false,
    routes: false,
  });
  const [permissions, setPermissions] = useState<Record<string, boolean>>({});
  const permissionEnabledCount = Object.values(permissions).filter(Boolean).length;

  const safeBack = () => {
    if (router.canGoBack()) {
      router.back();
      return;
    }
    router.replace('/(auth)/register');
  };

  const finish = async () => {
    if (joinMode === 'join' && !profileRole) return;
    const mode = joinMode !== 'join' ? 'parents' :
      profileRole === 'woman' ? 'women' :
      profileRole === 'child' ? 'kids' :
      profileRole === 'senior' ? 'senior' :
      profileRole === 'family' ? 'family' :
      'parents';
    await startLocalPreview(mode);
    router.replace('/(tabs)/home');
  };

  const goNext = () => {
    if (step >= TOTAL_STEPS) {
      finish();
      return;
    }
    setStep((value) => value + 1);
  };

  const goBack = () => {
    if (step <= 2) {
      safeBack();
      return;
    }
    setStep((value) => value - 1);
  };

  return (
    <SafeAreaView style={styles.safe}>
      <LinearGradient colors={['#0EA5E9', '#22C55E']} start={{ x: 0, y: 0 }} end={{ x: 1, y: 0 }} style={styles.topRule} />
      <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === 'ios' ? 'padding' : 'height'}>
      <ScrollView
        contentContainerStyle={styles.scroll}
        keyboardShouldPersistTaps="handled"
        keyboardDismissMode="on-drag"
        showsVerticalScrollIndicator={false}
      >
        {step <= TOTAL_STEPS ? <Header step={step} onBack={goBack} dark={false} /> : null}

        {step === 2 ? (
          <SetupFrame
            icon="mail"
            title="What's your email?"
            subtitle="We'll use it for account security, password recovery, and important safety alerts."
          >
            <Field label="EMAIL ADDRESS" icon="mail-outline" placeholder="Enter your email" value={email} onChangeText={setEmail} keyboardType="email-address" />
            <PrimaryButton title="Continue" onPress={goNext} disabled={!email.includes('@')} />
          </SetupFrame>
        ) : null}

        {step === 3 ? (
          <SetupFrame
            icon="id-card"
            title="What's your name?"
            subtitle="This helps your family identify you across the platform."
          >
            <Field label="FIRST NAME" icon="person-outline" placeholder="Enter first name" value={firstName} onChangeText={setFirstName} />
            <Field label="LAST NAME" icon="person-outline" placeholder="Enter last name" value={lastName} onChangeText={setLastName} />
            <PrimaryButton title="Continue" onPress={goNext} disabled={!firstName.trim()} />
          </SetupFrame>
        ) : null}

        {step === 4 ? (
          <View style={styles.section}>
            <Text style={styles.bigTitle}>How are you joining NISCHINT?</Text>
            <Text style={styles.subtitle}>Choose how you would like to get started.</Text>
            <ChoiceCard
              selected={joinMode === 'create'}
              variant="create"
              icon="shield-checkmark-outline"
              title="Create a Family Circle"
              desc="Create and manage protection for your loved ones."
              tags={['Create Family Circle', 'Add Family Members', 'Receive Alerts', 'Manage Safety Settings', 'Monitor Routes', 'Emergency Escalation']}
              role="For: Parent · Guardian · Caregiver"
              onPress={() => setJoinMode('create')}
            />
            <ChoiceCard
              selected={joinMode === 'join'}
              variant="join"
              icon="link-outline"
              title="Join an Existing Family Circle"
              desc="Join a protected family network using a QR Code or Invite Code."
              tags={['Connect to Guardian', 'Share Safety Status', 'Receive Protection', 'Emergency Support', 'Route Monitoring']}
              role="For: Child · Women · Senior Citizen"
              onPress={() => setJoinMode('join')}
            />
            <PrimaryButton title="Continue" onPress={goNext} disabled={!joinMode} tone={joinMode === 'join' ? 'green' : 'blue'} />
          </View>
        ) : null}

        {step === 5 ? (
          <View style={styles.section}>
            {joinMode === 'create' ? (
              <>
                <View style={styles.familyOrbit}>
                  <View style={styles.orbitRing} />
                  <View style={[styles.familyBubble, styles.familyBubbleLeft]}>
                    <Ionicons name="person" size={24} color="#0F172A" />
                    <Text style={styles.bubbleName}>Aarav</Text>
                    <Text style={styles.bubbleRole}>Child</Text>
                  </View>
                  <View style={[styles.familyBubble, styles.familyBubbleTop]}>
                    <Ionicons name="person" size={24} color="#0F172A" />
                    <Text style={styles.bubbleName}>dfxcghbj</Text>
                    <Text style={styles.bubbleRole}>Mom</Text>
                  </View>
                  <View style={[styles.familyBubble, styles.familyBubbleRight]}>
                    <Ionicons name="person" size={24} color="#0F172A" />
                    <Text style={styles.bubbleName}>Rajesh</Text>
                    <Text style={styles.bubbleRole}>Dad</Text>
                  </View>
                </View>
                <Text style={styles.welcomeText}>WELCOME, DFXCGHBJ</Text>
                <Text style={styles.guardianTitle}>You're the Guardian of Your Family Circle</Text>
                <Text style={styles.centerSubtitle}>Create a secure safety network for children, women, and senior citizens.</Text>
                {[
                  ['flash-outline', 'AI Monitoring', 'Smart threat detection 24/7'],
                  ['location-outline', 'Route Monitoring', 'Track safe paths and zones'],
                  ['shield-outline', 'Emergency Protection', 'Instant SOS and panic alerts'],
                  ['people-outline', 'Guardian Alerts', 'All guardians notified instantly'],
                  ['notifications-outline', 'Real-Time Notifications', 'Never miss a safety update'],
                ].map(([icon, title, desc]) => (
                  <FeatureRow key={title} icon={icon as any} title={title} desc={desc} />
                ))}
                <View style={styles.howCard}>
                  <Text style={styles.howTitle}>HOW IT WORKS</Text>
                  <View style={styles.howRow}>
                    <View style={styles.howItem}>
                      <View style={styles.howIcon}><Ionicons name="radio-button-on-outline" size={28} color="#F0447A" /></View>
                      <Text style={styles.howText}>Create{'\n'}Circle</Text>
                    </View>
                    <Ionicons name="chevron-forward" size={22} color="#CBD5E1" />
                    <View style={styles.howItem}>
                      <View style={styles.howIcon}><Ionicons name="people" size={28} color="#6D28D9" /></View>
                      <Text style={styles.howText}>Invite{'\n'}Member</Text>
                    </View>
                    <Ionicons name="chevron-forward" size={22} color="#CBD5E1" />
                    <View style={styles.howItem}>
                      <View style={styles.howIcon}><Ionicons name="shield-checkmark" size={28} color="#0EA5E9" /></View>
                      <Text style={styles.howText}>Activate{'\n'}Protection</Text>
                    </View>
                  </View>
                </View>
                <PrimaryButton title="Continue" onPress={goNext} />
              </>
            ) : (
              <>
                <Text style={styles.bigTitle}>Join Your Family Circle</Text>
                <Text style={styles.subtitle}>Connect securely to your guardian's protection network.</Text>
                <View style={styles.joinMethodRow}>
                  <JoinMethodCard
                    selected={joinMethod === 'qr'}
                    icon="camera"
                    title="Scan QR Code"
                    desc="Scan a QR shared by your guardian"
                    onPress={() => setJoinMethod('qr')}
                  />
                  <JoinMethodCard
                    selected={joinMethod === 'code'}
                    icon="key"
                    title="Enter Invite Code"
                    desc="Enter a 6-digit invitation code"
                    onPress={() => {
                      setJoinMethod('code');
                      setTimeout(() => inviteInputRef.current?.focus(), 120);
                    }}
                  />
                </View>
                {joinMethod === 'qr' ? (
                  <View style={styles.qrPanel}>
                    <View style={styles.cornerQrFrame}>
                      <View style={[styles.cornerMark, styles.cornerTopLeft]} />
                      <View style={[styles.cornerMark, styles.cornerTopRight]} />
                      <View style={[styles.cornerMark, styles.cornerBottomLeft]} />
                      <View style={[styles.cornerMark, styles.cornerBottomRight]} />
                      <View style={styles.qrCodeTile}>
                        <Ionicons name="qr-code" size={82} color="#111827" />
                      </View>
                    </View>
                    <Text style={styles.qrTitle}>Point your camera at the QR</Text>
                    <Text style={styles.qrSub}>Your guardian can share their QR code from the NISCHINT app.</Text>
                    <TouchableOpacity activeOpacity={0.86} onPress={goNext} style={styles.openCameraButton}>
                      <Ionicons name="qr-code-outline" size={22} color="#FFFFFF" />
                      <Text style={styles.openCameraText}>Open Camera</Text>
                    </TouchableOpacity>
                  </View>
                ) : joinMethod === 'code' ? (
                  <View style={styles.codePanel}>
                    <Text style={styles.codeTitle}>Enter your 6-digit invite code</Text>
                    <Text style={styles.qrSub}>Ask your guardian to share their invite code from NISCHINT.</Text>
                    <TouchableOpacity activeOpacity={0.9} onPress={() => inviteInputRef.current?.focus()} style={styles.codeBoxes}>
                      {Array.from({ length: 6 }).map((_, index) => (
                        <View key={index} style={[styles.codeBox, inviteCode[index] && styles.codeBoxFilled]}>
                          <Text style={styles.codeDigit}>{inviteCode[index] || ''}</Text>
                        </View>
                      ))}
                      <TextInput
                        ref={inviteInputRef}
                        value={inviteCode}
                        onChangeText={(value) => setInviteCode(value.replace(/\D/g, '').slice(0, 6))}
                        keyboardType="number-pad"
                        maxLength={6}
                        caretHidden
                        style={styles.hiddenCodeInput}
                      />
                    </TouchableOpacity>
                    <PrimaryButton title="Continue" onPress={goNext} disabled={inviteCode.length < 6} />
                  </View>
                ) : (
                  <View style={styles.joinEmptyState}>
                    <View style={styles.linkBadge}>
                      <Ionicons name="link-outline" size={42} color="#A78BFA" />
                    </View>
                    <Text style={styles.joinEmptyText}>Choose how you'd like to connect to your guardian's family circle above.</Text>
                  </View>
                )}
              </>
            )}
          </View>
        ) : null}

        {step === 6 ? (
          <View style={styles.section}>
            {joinMode === 'join' ? (
              <>
                <View style={styles.connectedBanner}>
                  <View style={styles.connectedIcon}>
                    <Ionicons name="shield-checkmark-outline" size={28} color="#FFFFFF" />
                  </View>
                  <View>
                    <Text style={styles.connectedTitle}>You're Connected!</Text>
                    <Text style={styles.connectedSub}>Successfully joined the family circle.</Text>
                  </View>
                </View>
                <Text style={styles.bigTitle}>Select who you are within this family network</Text>
                <Text style={styles.subtitle}>This helps your guardian understand how to best protect you.</Text>
                <View style={styles.roleGrid}>
                  {[
                    ['child', 'Child', 'I am a child being protected and monitored by my guardians.'],
                    ['woman', 'Woman', 'I want to stay connected and share my safety status with trusted family members.'],
                    ['senior', 'Senior Citizen', 'I want family members to stay connected and support me whenever needed.'],
                    ['family', 'Family Member', 'I am joining an existing Family Circle and want to stay protected and connected.'],
                  ].map(([key, title, desc]) => (
                    <RoleOption
                      key={key}
                      selected={profileRole === key}
                      role={key}
                      title={title}
                      desc={desc}
                      onPress={() => setProfileRole(key as 'child' | 'woman' | 'senior' | 'family')}
                    />
                  ))}
                </View>
                <TouchableOpacity
                  activeOpacity={0.86}
                  onPress={() => setStep(7)}
                  disabled={!profileRole}
                  style={[
                    styles.roleContinue,
                    !profileRole && styles.primaryDisabled,
                  ]}
                >
                  {profileRole ? (
                    <LinearGradient
                      colors={profileRole === 'senior' ? ['#F59E0B', '#FCD34D'] : [getRoleTheme(profileRole).primary, getRoleTheme(profileRole).primary]}
                      start={{ x: 0, y: 0 }}
                      end={{ x: 1, y: 0 }}
                      style={styles.roleContinueGradient}
                    >
                      <Text style={styles.primaryText}>Continue</Text>
                    </LinearGradient>
                  ) : (
                    <Text style={styles.primaryText}>Continue</Text>
                  )}
                </TouchableOpacity>
              </>
            ) : (
              <>
                <View style={styles.protectionOrbit}>
                  <View style={styles.planOrbitOuter} />
                  <View style={styles.planOrbitInner} />
                  <View style={styles.planOrbitCenter}>
                    <Ionicons name="shield-checkmark" size={28} color="#0EA5E9" />
                    <Text style={styles.planOrbitYou}>You</Text>
                  </View>
                  <View style={[styles.planPerson, styles.planPersonTop]}>
                    <Ionicons name="person" size={20} color="#6D28D9" />
                    <Text style={styles.planPersonText}>Co-Guardian</Text>
                  </View>
                  <View style={[styles.planPerson, styles.planPersonLeft]}>
                    <Ionicons name="accessibility" size={20} color="#F59E0B" />
                    <Text style={styles.planPersonText}>Senior</Text>
                  </View>
                  <View style={[styles.planPerson, styles.planPersonRight]}>
                    <Ionicons name="happy-outline" size={20} color="#22C55E" />
                    <Text style={styles.planPersonText}>Child</Text>
                  </View>
                  <View style={[styles.planPerson, styles.planPersonBottom]}>
                    <Ionicons name="female" size={20} color="#8B5CF6" />
                    <Text style={styles.planPersonText}>Woman</Text>
                  </View>
                </View>
                <Text style={styles.planTitle}>Choose Your Protection Plan</Text>
                <Text style={styles.centerSubtitle}>Create a private safety network and stay connected with the people who matter most.</Text>
                <View style={styles.premiumCard}>
                  <View style={styles.premiumHeader}>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.popularPill}>Most Popular</Text>
                      <Text style={styles.planName}>Premium Family Circle</Text>
                    </View>
                    <View style={styles.priceBlock}>
                      <Text style={styles.rupeePrice}>₹299</Text>
                      <Text style={styles.perMonth}>per month</Text>
                    </View>
                  </View>
                  {[
                    '1 Primary Guardian',
                    '1 Co-Guardian',
                    '1 Protected Member',
                    'AI Safety Monitoring',
                    'Route Monitoring',
                    'Emergency SOS Alerts',
                    'QR Code Linking',
                    'Real-Time Guardian Notifications',
                    'Emergency Escalation',
                    'Family Safety Dashboard',
                  ].map((item) => (
                    <View key={item} style={styles.planFeatureRow}>
                      <Ionicons name="checkmark" size={18} color="#FFFFFF" style={styles.featureCheck} />
                      <Text style={styles.planFeatureText}>{item}</Text>
                    </View>
                  ))}
                  <Text style={styles.pricingNote}>Pricing subject to change</Text>
                </View>
                <PrimaryButton title="Start Premium Protection" onPress={() => setStep(7)} />
                <TouchableOpacity onPress={() => setStep(7)} activeOpacity={0.8}>
                  <Text style={styles.freePlanText}>Continue with Free Plan</Text>
                </TouchableOpacity>
              </>
            )}
          </View>
        ) : null}

        {step === 7 ? (
          <View style={styles.privacyScreen}>
            <View style={styles.privacyHero}>
              <View style={styles.privacyBrandRow}>
                <NischintLogo size={42} />
                <View style={{ flex: 1 }}>
                  <Text style={styles.privacyHeroTitle}>NISCHINT</Text>
                  <Text style={styles.privacyHeroSub}>Data Protection & Privacy</Text>
                </View>
                <View style={styles.privacyStepPill}>
                  <Text style={styles.privacyStepText}>Step 1/2</Text>
                </View>
              </View>
            </View>

            <View style={styles.privacyBody}>
              <Text style={styles.privacyMainTitle}>Your Privacy Matters</Text>
              <Text style={styles.privacyIntro}>
                NISCHINT complies with the Digital Personal Data Protection Act 2023 (DPDP). Review and provide consent below.
              </Text>

              <View style={styles.dpdpWideCard}>
                <Ionicons name="shield-outline" size={26} color="#3B82F6" />
                <View style={{ flex: 1 }}>
                  <Text style={styles.dpdpWideTitle}>DPDP Act 2023 Compliant</Text>
                  <Text style={styles.dpdpWideSub}>Your data is protected under Indian law</Text>
                </View>
              </View>

              <Text style={styles.privacySectionLabel}>REQUIRED</Text>
              <RequiredConsent title="I agree to Privacy Policy" icon="clipboard-outline" />
              <RequiredConsent title="I agree to Terms & Conditions" icon="document-text-outline" />

              <Text style={styles.privacySectionLabel}>OPTIONAL - OPT IN</Text>
              <PrivacyOptRow
                enabled={privacy.ai}
                icon="sparkles-outline"
                title="AI Monitoring"
                desc="NISCHINT AI detects distress patterns and unusual behavior for your safety"
                onPress={() => setPrivacy((value) => ({ ...value, ai: !value.ai }))}
              />
              <PrivacyOptRow
                enabled={privacy.location}
                icon="location"
                title="Location Sharing"
                desc="Real-time location tracking for safe zone alerts and live guardian monitoring"
                onPress={() => setPrivacy((value) => ({ ...value, location: !value.location }))}
              />
              <PrivacyOptRow
                enabled={privacy.microphone}
                icon="mic-outline"
                title="Microphone Detection"
                desc="AI detects screams, distress sounds, and voice trigger words"
                onPress={() => setPrivacy((value) => ({ ...value, microphone: !value.microphone }))}
              />
              <PrivacyOptRow
                enabled={privacy.wearable}
                icon="watch-outline"
                title="Wearable Integration"
                desc="Connect smart watch, safety band, or emergency keychain"
                onPress={() => setPrivacy((value) => ({ ...value, wearable: !value.wearable }))}
              />
              <PrivacyOptRow
                enabled={privacy.background}
                icon="shield"
                title="Background Monitoring"
                desc="Continuous protection even when app is in background"
                onPress={() => setPrivacy((value) => ({ ...value, background: !value.background }))}
              />
              <PrivacyOptRow
                enabled={privacy.routes}
                icon="map-outline"
                title="Route Monitoring"
                desc="Track journeys, detect deviations, and monitor school routes"
                onPress={() => setPrivacy((value) => ({ ...value, routes: !value.routes }))}
              />

              <Text style={styles.privacyHint}>You can enable or disable these anytime from Settings {'->'} Privacy & Consent</Text>
              <TouchableOpacity onPress={() => setStep(8)} activeOpacity={0.82}>
                <Text style={styles.skipOptional}>Skip optional for now {'->'}</Text>
              </TouchableOpacity>
              <PrimaryButton title="Continue to Permissions" onPress={() => setStep(8)} />
              <TouchableOpacity onPress={finish} activeOpacity={0.82}>
                <Text style={styles.declineText}>Decline & Exit</Text>
              </TouchableOpacity>
            </View>
          </View>
        ) : null}

        {step === 8 ? (
          <View style={styles.privacyScreen}>
            <View style={styles.privacyHero}>
              <View style={styles.privacyBrandRow}>
                <NischintLogo size={42} />
                <View style={{ flex: 1 }}>
                  <Text style={styles.privacyHeroTitle}>NISCHINT</Text>
                  <Text style={styles.privacyHeroSub}>Data Protection & Privacy</Text>
                </View>
                <View style={styles.privacyStepPill}>
                  <Text style={styles.privacyStepText}>Step 2/2</Text>
                </View>
              </View>
            </View>

            <View style={styles.privacyBody}>
              <View style={styles.permissionTitleRow}>
                <View style={styles.permissionShield}>
                  <Ionicons name="shield-checkmark-outline" size={34} color="#FFFFFF" />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.privacyMainTitle}>App Permissions</Text>
                  <Text style={styles.permissionIntro}>Grant permissions to enable real-time protection.</Text>
                </View>
              </View>

              <View style={styles.permissionProgress}>
                <Text style={styles.permissionProgressTitle}>Protection Setup Progress</Text>
                <Text style={styles.permissionProgressText}>
                  <Text style={styles.permissionProgressCount}>{permissionEnabledCount} of 6</Text> Optional Features Enabled
                </Text>
              </View>

              {[
                ['location', 'location', 'Location', 'Required', 'Allow', ['Required for safe zones', 'Live guardian tracking', 'Route deviation alerts']],
                ['notifications', 'notifications', 'Notifications', 'Required', 'Allow', ['SOS emergency alerts', 'Safety check-in reminders', 'Guardian notifications']],
                ['background', 'flash', 'Background Activity', 'Optional', 'Skip', ['Continuous background protection', 'Always-on monitoring', 'Recommended for full safety']],
                ['microphone', 'mic', 'Microphone', 'Optional', 'Skip', ['AI distress sound detection', 'Scream and panic detection', 'Voice trigger words']],
                ['camera', 'camera', 'Camera', 'Optional', 'Skip', ['QR code scanning only', 'No video recording', 'One-time scan use']],
                ['bluetooth', 'radio-button-on', 'Bluetooth', 'Optional', 'Skip', ['Wearable device pairing', 'Safety band connectivity', 'Emergency keychain support']],
              ].map(([key, icon, title, requirement, action, bullets]) => (
                <PermissionRow
                  key={key as string}
                  icon={icon}
                  title={title}
                  requirement={requirement}
                  action={permissions[key as string] ? 'Done' : action}
                  enabled={permissions[key as string]}
                  bullets={bullets}
                  onPress={() => setPermissions((value) => ({ ...value, [key as string]: !value[key as string] }))}
                />
              ))}

              <TouchableOpacity activeOpacity={0.86} onPress={finish} style={styles.activateButton}>
                <LinearGradient colors={['#0EA5E9', '#22C55E']} start={{ x: 0, y: 0 }} end={{ x: 1, y: 0 }} style={styles.activateGradient}>
                  <Ionicons name="checkbox" size={20} color="#FFFFFF" />
                  <Text style={styles.activateText}>Activate Protection</Text>
                </LinearGradient>
              </TouchableOpacity>
              <TouchableOpacity onPress={() => setStep(7)} activeOpacity={0.82}>
                <Text style={styles.backConsentText}>{'<-'} Back to Consent</Text>
              </TouchableOpacity>
            </View>
          </View>
        ) : null}
      </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

function Header({ step, onBack, dark }: { step: number; onBack: () => void; dark?: boolean }) {
  return (
    <View style={[styles.header, dark && styles.headerDark]}>
      <TouchableOpacity onPress={onBack} style={styles.back}>
        <Ionicons name="chevron-back" size={21} color={dark ? '#FFFFFF' : '#0F172A'} />
      </TouchableOpacity>
      <View style={styles.headerLogo}>
        <NischintLogo size={34} />
      </View>
      <View style={styles.stepPill}>
        <Text style={styles.stepText}>{step} of {TOTAL_STEPS}</Text>
      </View>
      <View style={styles.progressTrack}>
        <View style={[styles.progressFill, { width: `${(step / TOTAL_STEPS) * 100}%` }]} />
      </View>
    </View>
  );
}

function SetupFrame({ icon, title, subtitle, children }: any) {
  return (
    <View style={styles.section}>
      <View style={styles.illustration}>
        <Ionicons name={icon} size={56} color="#0EA5E9" />
        <View style={styles.successBubble}>
          <Ionicons name="checkmark" size={24} color="#FFFFFF" />
        </View>
      </View>
      <Text style={styles.bigTitle}>{title}</Text>
      <Text style={styles.subtitle}>{subtitle}</Text>
      {children}
    </View>
  );
}

function Field({ label, icon, ...props }: any) {
  return (
    <View style={styles.fieldGroup}>
      <Text style={styles.label}>{label}</Text>
      <View style={styles.field}>
        <Ionicons name={icon} size={20} color="#CBD5E1" />
        <TextInput {...props} style={styles.input} placeholderTextColor="#CBD5E1" autoCapitalize="none" />
      </View>
    </View>
  );
}

function PrimaryButton({ title, onPress, disabled, tone = 'blue' }: { title: string; onPress: () => void; disabled?: boolean; tone?: 'blue' | 'green' }) {
  return (
    <TouchableOpacity activeOpacity={0.86} onPress={onPress} disabled={disabled} style={[styles.primary, tone === 'green' && styles.primaryGreen, disabled && styles.primaryDisabled]}>
      <Text style={styles.primaryText}>{title}</Text>
    </TouchableOpacity>
  );
}

function ChoiceCard({ selected, variant, icon, title, desc, tags, role, onPress }: any) {
  const isJoin = variant === 'join';
  const activeColor = isJoin ? '#22C55E' : '#0EA5E9';
  const activeBg = isJoin ? '#F0FDF4' : '#EFF8FF';
  const tagStyle = isJoin ? styles.tagGreen : styles.tagBlue;
  return (
    <TouchableOpacity
      activeOpacity={0.9}
      onPress={onPress}
      style={[
        styles.choiceCard,
        selected && styles.choiceSelected,
        selected && { borderColor: activeColor, backgroundColor: activeBg, shadowColor: activeColor },
      ]}
    >
      <View style={styles.choiceTop}>
        <View style={[styles.choiceIcon, { backgroundColor: activeBg }]}><Ionicons name={icon} size={26} color={activeColor} /></View>
        <Text style={styles.choiceTitle}>{title}</Text>
        <Ionicons name={selected ? 'checkmark-circle' : 'ellipse-outline'} size={27} color={selected ? activeColor : '#D8DEE8'} />
      </View>
      <Text style={styles.choiceDesc}>{desc}</Text>
      <View style={styles.tags}>{tags.map((tag: string) => <Text key={tag} style={[styles.tag, tagStyle]}>• {tag}</Text>)}</View>
      <Text style={[styles.roleTag, tagStyle]}><Ionicons name="people-outline" size={13} /> {role}</Text>
      {selected ? <View style={[styles.choiceBottomRule, { backgroundColor: activeColor }]} /> : null}
    </TouchableOpacity>
  );
}

function FeatureRow({ icon, title, desc }: { icon: any; title: string; desc: string }) {
  return (
    <View style={styles.featureRow}>
      <View style={styles.featureIcon}><Ionicons name={icon} size={24} color="#0EA5E9" /></View>
      <View style={styles.featureCopy}>
        <Text style={styles.featureTitle}>{title}</Text>
        <Text style={styles.featureDesc}>{desc}</Text>
      </View>
      <Ionicons name="checkmark-circle" size={25} color="#22C5C6" />
    </View>
  );
}

function JoinMethodCard({ selected, icon, title, desc, onPress }: any) {
  return (
    <TouchableOpacity activeOpacity={0.88} onPress={onPress} style={[styles.joinMethodCard, selected && styles.joinMethodSelected]}>
      <Ionicons name={icon} size={30} color={selected ? '#22C55E' : '#7C8AA2'} />
      <Text style={styles.joinMethodTitle}>{title}</Text>
      <Text style={styles.joinMethodDesc}>{desc}</Text>
      {selected ? <Ionicons name="checkmark-circle" size={18} color="#22C55E" /> : null}
    </TouchableOpacity>
  );
}

function getRoleTheme(role: 'child' | 'woman' | 'senior' | 'family') {
  if (role === 'woman') return { primary: '#EC4899', bg: '#FDF2F8', shadow: '#DB2777' };
  if (role === 'senior') return { primary: '#F59E0B', bg: '#FFF7ED', shadow: '#D97706' };
  if (role === 'family') return { primary: '#7C8A9E', bg: '#F8FAFC', shadow: '#475569' };
  return { primary: '#A78BFA', bg: '#F7F1FF', shadow: '#8B5CF6' };
}

function RoleOption({ selected, role, title, desc, onPress }: any) {
  const theme = getRoleTheme(role);
  return (
    <TouchableOpacity
      activeOpacity={0.9}
      onPress={onPress}
      style={[
        styles.roleCard,
        selected && styles.roleSelected,
        selected && { borderColor: theme.primary, backgroundColor: theme.bg, shadowColor: theme.shadow },
      ]}
    >
      {selected ? (
        <View style={[styles.roleCheck, { backgroundColor: theme.primary }]}>
          <Ionicons name="checkmark" size={16} color="#FFFFFF" />
        </View>
      ) : null}
      <RoleScene role={role} />
      <Text style={[styles.roleTitle, selected && { color: theme.primary }]}>{title}</Text>
      <Text style={styles.roleDesc}>{desc}</Text>
    </TouchableOpacity>
  );
}

function RoleScene({ role }: { role: 'child' | 'woman' | 'senior' | 'family' }) {
  const bg = role === 'child' ? '#DDF6FF' : role === 'woman' ? '#FCE7F3' : role === 'senior' ? '#FFF2B8' : '#F7E7CF';
  return (
    <View style={[styles.roleArt, { backgroundColor: bg }]}>
      <View style={styles.sceneGround} />
      {role === 'child' ? (
        <>
          <View style={[styles.sceneTree, { left: 8, bottom: 18 }]} />
          <View style={[styles.sceneSun, { right: 8, top: 8 }]} />
          <View style={styles.schoolBlock}><Text style={styles.schoolText}>SCHOOL</Text></View>
          <Text style={[styles.sceneEmoji, { left: 42, top: 28 }]}>👧</Text>
          <Text style={[styles.sceneEmoji, { left: 92, top: 29 }]}>👦</Text>
        </>
      ) : null}
      {role === 'woman' ? (
        <>
          <View style={[styles.cityBlock, { left: 6, height: 36 }]} />
          <View style={[styles.cityBlock, { right: 8, height: 42 }]} />
          <Text style={[styles.sceneEmoji, { left: 48, top: 29 }]}>👩</Text>
          <Text style={[styles.sceneEmoji, { left: 104, top: 30 }]}>👨‍💼</Text>
        </>
      ) : null}
      {role === 'senior' ? (
        <>
          <View style={[styles.sceneTree, { left: 10, bottom: 18 }]} />
          <View style={[styles.sceneTree, { right: 8, bottom: 18 }]} />
          <View style={styles.bench} />
          <Text style={[styles.sceneEmoji, { left: 54, top: 28 }]}>👴</Text>
          <Text style={[styles.sceneEmoji, { left: 96, top: 28 }]}>👵</Text>
        </>
      ) : null}
      {role === 'family' ? (
        <>
          <Text style={[styles.sceneEmoji, { left: 15, top: 29 }]}>👨</Text>
          <Text style={[styles.sceneEmoji, { left: 54, top: 29 }]}>👩</Text>
          <Text style={[styles.sceneEmoji, { left: 94, top: 30 }]}>👦</Text>
          <Text style={[styles.sceneEmoji, { left: 132, top: 30 }]}>👧</Text>
        </>
      ) : null}
    </View>
  );
}

function PersonFigure({ x, y, shirt, pants = '#1F2937', skirt, bag, senior }: any) {
  return (
    <View style={[styles.personFigure, { left: x, top: y }]}>
      <View style={[styles.personHair, senior && styles.seniorHair]} />
      <View style={styles.personHead} />
      <View style={[styles.personBody, { backgroundColor: shirt }]} />
      {bag ? <View style={styles.personBag} /> : null}
      <View style={styles.personLegRow}>
        <View style={[styles.personLeg, skirt ? styles.personSkirtLeg : null, { backgroundColor: pants }]} />
        <View style={[styles.personLeg, skirt ? styles.personSkirtLeg : null, { backgroundColor: pants }]} />
      </View>
    </View>
  );
}

function RequiredConsent({ title, icon }: { title: string; icon: keyof typeof Ionicons.glyphMap }) {
  return (
    <View style={styles.requiredConsentRow}>
      <View style={styles.requiredCheck}>
        <Ionicons name="checkmark" size={22} color="#FFFFFF" />
      </View>
      <View style={styles.requiredCopy}>
        <Text style={styles.requiredConsentTitle}>{title}</Text>
        <Text style={styles.requiredSmall}>Required</Text>
      </View>
      <Ionicons name={icon} size={24} color="#B994A5" />
    </View>
  );
}

function PrivacyOptRow({ enabled, icon, title, desc, onPress }: any) {
  return (
    <TouchableOpacity activeOpacity={0.86} onPress={onPress} style={styles.privacyOptRow}>
      <View style={[styles.switchTrack, enabled && styles.switchTrackOn]}>
        <View style={[styles.switchKnob, enabled && styles.switchKnobOn]} />
      </View>
      <Ionicons name={icon} size={22} color="#6D7FA0" />
      <View style={styles.privacyOptCopy}>
        <Text style={styles.privacyOptTitle}>{title}</Text>
        <Text style={styles.privacyOptDesc}>{desc}</Text>
      </View>
    </TouchableOpacity>
  );
}

function PermissionRow({ icon, title, requirement, action, enabled, bullets, onPress }: any) {
  const isRequired = requirement === 'Required';
  return (
    <View style={styles.permissionCard}>
      <Ionicons name={icon} size={30} color={icon === 'location' ? '#EC4899' : icon === 'notifications' ? '#F59E0B' : '#7C8AA2'} />
      <View style={styles.permissionCopy}>
        <View style={styles.permissionCardTop}>
          <Text style={styles.permissionTitle}>{title}</Text>
          <Text style={[styles.permissionBadge, isRequired ? styles.permissionBadgeRequired : styles.permissionBadgeOptional]}>
            {requirement}
          </Text>
        </View>
        {bullets.map((item: string) => (
          <Text key={item} style={styles.permissionBullet}>• {item}</Text>
        ))}
      </View>
      <TouchableOpacity activeOpacity={0.84} onPress={onPress} style={[styles.permissionAction, enabled && styles.permissionActionDone, !isRequired && !enabled && styles.permissionActionSkip]}>
        <Text style={[styles.permissionActionText, !isRequired && !enabled && styles.permissionActionSkipText]}>{action}</Text>
      </TouchableOpacity>
    </View>
  );
}

function ConsentRow({ checked, title, desc, required, onPress }: any) {
  return (
    <TouchableOpacity activeOpacity={0.88} onPress={onPress} disabled={required} style={styles.consentRow}>
      <View style={[styles.toggle, checked && styles.toggleOn]}>
        {checked ? <Ionicons name="checkmark" size={18} color="#FFFFFF" /> : null}
      </View>
      <View style={styles.consentCopy}>
        <Text style={styles.consentTitle}>{title}</Text>
        {required ? <Text style={styles.required}>Required</Text> : null}
        {desc ? <Text style={styles.consentDesc}>{desc}</Text> : null}
      </View>
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: '#F8FAFC' },
  flex: { flex: 1 },
  topRule: { height: 5 },
  scroll: { flexGrow: 1, paddingHorizontal: 24, paddingBottom: 140 },
  header: { paddingTop: 24, paddingBottom: 22 },
  headerDark: { marginHorizontal: -24, paddingHorizontal: 24, backgroundColor: '#071225' },
  back: { width: 42, height: 42, borderRadius: 21, alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(241,245,249,0.92)' },
  headerLogo: { position: 'absolute', top: 31, alignSelf: 'center' },
  stepPill: { position: 'absolute', top: 29, right: 0, paddingHorizontal: 14, height: 30, borderRadius: 15, justifyContent: 'center', backgroundColor: '#FFFFFF' },
  stepText: { color: '#0EA5E9', fontSize: 13, fontWeight: '900' },
  progressTrack: { height: 4, marginTop: 26, borderRadius: 2, backgroundColor: '#E2E8F0', overflow: 'hidden' },
  progressFill: { height: 4, backgroundColor: '#22D3EE' },
  section: { paddingTop: 24, gap: 14 },
  illustration: { width: 128, height: 128, alignSelf: 'center', borderRadius: 34, alignItems: 'center', justifyContent: 'center', backgroundColor: '#E0F2FE', marginBottom: 40 },
  successBubble: { position: 'absolute', right: -12, top: -12, width: 44, height: 44, borderRadius: 22, alignItems: 'center', justifyContent: 'center', backgroundColor: '#22C55E' },
  bigTitle: { color: '#0B1120', fontSize: 34, lineHeight: 39, fontWeight: '900' },
  planTitle: { color: '#0B1120', fontSize: 28, lineHeight: 34, fontWeight: '900', textAlign: 'center' },
  guardianTitle: { color: '#0B1120', fontSize: 28, lineHeight: 34, fontWeight: '900', textAlign: 'center' },
  welcomeText: { color: '#0EA5E9', fontSize: 15, letterSpacing: 4, fontWeight: '900', textAlign: 'center' },
  subtitle: { color: '#667085', fontSize: 17, lineHeight: 25, fontWeight: '600' },
  centerSubtitle: { color: '#667085', fontSize: 16, lineHeight: 24, fontWeight: '600', textAlign: 'center' },
  familyOrbit: { height: 220, alignItems: 'center', justifyContent: 'center', marginTop: 4, marginBottom: 2 },
  orbitRing: { width: 190, height: 190, borderRadius: 95, borderWidth: 1, borderColor: '#DCEBFA', backgroundColor: 'rgba(240,249,255,0.55)' },
  familyBubble: { position: 'absolute', width: 62, minHeight: 82, alignItems: 'center' },
  familyBubbleLeft: { left: '27%', bottom: 18 },
  familyBubbleTop: { right: '27%', top: 18 },
  familyBubbleRight: { right: '25%', bottom: 20 },
  bubbleName: { color: '#CBD5E1', fontSize: 12, fontWeight: '900', marginTop: 4 },
  bubbleRole: { color: '#0EA5E9', fontSize: 11, fontWeight: '900', marginTop: 2 },
  fieldGroup: { marginTop: 18 },
  label: { color: '#111827', fontSize: 13, fontWeight: '900', letterSpacing: 2, marginBottom: 10 },
  field: { minHeight: 64, borderRadius: 18, borderWidth: 1.8, borderColor: '#38BDF8', flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 18, backgroundColor: '#FFFFFF' },
  input: { flex: 1, minWidth: 0, color: '#0F172A', fontSize: 16, fontWeight: '700' },
  primary: { width: '100%', minHeight: 64, borderRadius: 18, alignItems: 'center', justifyContent: 'center', marginTop: 18, backgroundColor: '#18BDF2' },
  primaryGreen: { backgroundColor: '#22C55E' },
  primaryDisabled: { backgroundColor: '#BAEEF8' },
  primaryText: { color: '#FFFFFF', fontSize: 17, fontWeight: '900' },
  choiceCard: { borderRadius: 24, borderWidth: 1.4, borderColor: '#E2E8F0', backgroundColor: '#FFFFFF', padding: 20, gap: 14, shadowColor: '#0F172A', shadowOpacity: 0.06, shadowOffset: { width: 0, height: 8 }, shadowRadius: 18, elevation: 2 },
  choiceSelected: { borderWidth: 2.4, shadowOpacity: 0.18, shadowOffset: { width: 0, height: 12 }, shadowRadius: 22, elevation: 5 },
  choiceTop: { flexDirection: 'row', alignItems: 'center', gap: 14 },
  choiceIcon: { width: 54, height: 54, borderRadius: 18, alignItems: 'center', justifyContent: 'center', backgroundColor: '#E0F2FE' },
  choiceTitle: { flex: 1, color: '#0F172A', fontSize: 18, fontWeight: '900' },
  choiceDesc: { color: '#667085', fontSize: 15, lineHeight: 22, fontWeight: '600' },
  tags: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  tag: { fontSize: 12, fontWeight: '800', paddingHorizontal: 10, paddingVertical: 6, borderRadius: 12, overflow: 'hidden' },
  tagBlue: { color: '#0077E6', backgroundColor: '#E0F2FE' },
  tagGreen: { color: '#08A647', backgroundColor: '#DCFCE7' },
  roleTag: { alignSelf: 'flex-start', fontSize: 13, lineHeight: 18, fontWeight: '900', paddingHorizontal: 13, paddingVertical: 8, borderRadius: 14, overflow: 'hidden' },
  choiceBottomRule: { height: 4, borderRadius: 2, marginTop: 4 },
  featureRow: { minHeight: 80, borderRadius: 20, backgroundColor: '#FFFFFF', flexDirection: 'row', alignItems: 'center', paddingHorizontal: 18, gap: 14 },
  featureIcon: { width: 50, height: 50, borderRadius: 16, alignItems: 'center', justifyContent: 'center', backgroundColor: '#E0F2FE' },
  featureCopy: { flex: 1 },
  featureTitle: { color: '#0F172A', fontSize: 17, fontWeight: '900' },
  featureDesc: { color: '#667085', fontSize: 14, fontWeight: '600', marginTop: 4 },
  howCard: { borderRadius: 20, backgroundColor: '#FFFFFF', padding: 20, shadowColor: '#0F172A', shadowOpacity: 0.06, shadowOffset: { width: 0, height: 8 }, shadowRadius: 18, elevation: 3 },
  howTitle: { color: '#64748B', fontSize: 14, letterSpacing: 3, fontWeight: '900', marginBottom: 16 },
  howRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  howItem: { alignItems: 'center', width: 82 },
  howIcon: { width: 54, height: 54, borderRadius: 18, alignItems: 'center', justifyContent: 'center', backgroundColor: '#EAF7FF', marginBottom: 9 },
  howText: { color: '#0B1120', fontSize: 12, lineHeight: 14, fontWeight: '800', textAlign: 'center' },
  protectionOrbit: { height: 300, alignItems: 'center', justifyContent: 'center', marginTop: 4 },
  planOrbitOuter: { position: 'absolute', width: 212, height: 212, borderRadius: 106, borderWidth: 1, borderStyle: 'dashed', borderColor: '#CFE7FA' },
  planOrbitInner: { position: 'absolute', width: 132, height: 132, borderRadius: 66, borderWidth: 1, borderColor: '#DCEBFA', backgroundColor: 'rgba(224,242,254,0.4)' },
  planOrbitCenter: { width: 78, height: 78, borderRadius: 39, borderWidth: 4, borderColor: '#38BDF8', backgroundColor: '#E0F7FE', alignItems: 'center', justifyContent: 'center' },
  planOrbitYou: { color: '#0EA5E9', fontSize: 13, fontWeight: '900', marginTop: 2 },
  planPerson: { position: 'absolute', minWidth: 78, minHeight: 70, alignItems: 'center' },
  planPersonTop: { top: 28 },
  planPersonLeft: { left: 28, top: 126 },
  planPersonRight: { right: 28, top: 126 },
  planPersonBottom: { bottom: 20 },
  planPersonText: { color: '#52647C', fontSize: 12, fontWeight: '800', marginTop: 4 },
  premiumCard: { borderRadius: 24, borderWidth: 1.5, borderColor: '#BAE6FD', backgroundColor: '#FFFFFF', overflow: 'hidden', shadowColor: '#0EA5E9', shadowOpacity: 0.18, shadowOffset: { width: 0, height: 14 }, shadowRadius: 28, elevation: 5 },
  premiumHeader: { minHeight: 110, padding: 20, flexDirection: 'row', alignItems: 'flex-start', backgroundColor: '#F0FBFF' },
  popularPill: { alignSelf: 'flex-start', overflow: 'hidden', color: '#FFFFFF', fontSize: 13, fontWeight: '900', paddingHorizontal: 13, paddingVertical: 7, borderRadius: 15, backgroundColor: '#11B7F0', marginBottom: 14 },
  priceBlock: { alignItems: 'flex-end', marginLeft: 10 },
  rupeePrice: { color: '#0F172A', fontSize: 38, lineHeight: 44, fontWeight: '900' },
  planFeatureRow: { flexDirection: 'row', alignItems: 'center', gap: 13, paddingHorizontal: 24, paddingTop: 14 },
  featureCheck: { width: 25, height: 25, borderRadius: 13, textAlign: 'center', textAlignVertical: 'center', backgroundColor: '#22C5C6', overflow: 'hidden' },
  planFeatureText: { color: '#0F172A', fontSize: 16, fontWeight: '800' },
  pricingNote: { color: '#94A3B8', fontSize: 13, fontWeight: '700', textAlign: 'center', paddingTop: 18, paddingBottom: 22 },
  freePlanText: { color: '#57708C', fontSize: 16, fontWeight: '800', textAlign: 'center', paddingVertical: 14 },
  joinMethodRow: { flexDirection: 'row', gap: 14, marginTop: 10 },
  joinMethodCard: { flex: 1, minHeight: 162, borderRadius: 16, borderWidth: 1.4, borderColor: '#DCE5EF', backgroundColor: '#FFFFFF', padding: 14, alignItems: 'center', justifyContent: 'center', gap: 7 },
  joinMethodSelected: { borderColor: '#22C55E', backgroundColor: '#F0FDF4', shadowColor: '#22C55E', shadowOpacity: 0.2, shadowOffset: { width: 0, height: 10 }, shadowRadius: 22, elevation: 4 },
  joinMethodTitle: { color: '#0F172A', fontSize: 17, fontWeight: '900', textAlign: 'center' },
  joinMethodDesc: { color: '#667085', fontSize: 13, lineHeight: 18, fontWeight: '700', textAlign: 'center' },
  joinEmptyState: { minHeight: 310, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 36 },
  linkBadge: { width: 82, height: 82, borderRadius: 22, alignItems: 'center', justifyContent: 'center', backgroundColor: '#EEFDF5', marginBottom: 20 },
  joinEmptyText: { color: '#52647C', fontSize: 17, lineHeight: 26, fontWeight: '600', textAlign: 'center' },
  qrPanel: { minHeight: 350, alignItems: 'center', justifyContent: 'center', paddingTop: 22 },
  cornerQrFrame: { width: 184, height: 152, alignItems: 'center', justifyContent: 'center', marginTop: 2, marginBottom: 14 },
  qrCodeTile: { width: 118, height: 118, borderRadius: 16, alignItems: 'center', justifyContent: 'center', backgroundColor: '#FFFFFF', shadowColor: '#22C55E', shadowOpacity: 0.22, shadowOffset: { width: 0, height: 12 }, shadowRadius: 24, elevation: 4 },
  cornerMark: { position: 'absolute', width: 30, height: 30, borderColor: '#22C55E' },
  cornerTopLeft: { left: 8, top: 0, borderTopWidth: 3, borderLeftWidth: 3 },
  cornerTopRight: { right: 8, top: 0, borderTopWidth: 3, borderRightWidth: 3 },
  cornerBottomLeft: { left: 8, bottom: 0, borderBottomWidth: 3, borderLeftWidth: 3 },
  cornerBottomRight: { right: 8, bottom: 0, borderBottomWidth: 3, borderRightWidth: 3 },
  qrFrame: { width: 150, height: 150, borderRadius: 20, borderWidth: 3, borderColor: '#22C55E', alignItems: 'center', justifyContent: 'center', backgroundColor: '#FFFFFF' },
  qrTitle: { color: '#0F172A', fontSize: 18, fontWeight: '900', textAlign: 'center', marginTop: 8 },
  qrSub: { color: '#667085', fontSize: 15, lineHeight: 22, fontWeight: '600', textAlign: 'center', marginTop: 8 },
  openCameraButton: { width: '100%', minHeight: 70, borderRadius: 17, backgroundColor: '#2ED36E', flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 12, marginTop: 26 },
  openCameraText: { color: '#FFFFFF', fontSize: 20, fontWeight: '900' },
  codePanel: { width: '100%', minHeight: 280, alignItems: 'center', justifyContent: 'flex-start', paddingTop: 22 },
  codeTitle: { color: '#0F172A', fontSize: 18, lineHeight: 24, fontWeight: '900', textAlign: 'center', marginTop: 2 },
  codeBoxes: { flexDirection: 'row', gap: 9, marginTop: 26 },
  codeBox: { width: 52, height: 64, borderRadius: 17, borderWidth: 1.5, borderColor: '#D8E2EE', alignItems: 'center', justifyContent: 'center', backgroundColor: '#FFFFFF' },
  codeBoxFilled: { borderColor: '#22C55E', backgroundColor: '#F0FDF4' },
  codeDigit: { color: '#0F172A', fontSize: 22, fontWeight: '900', textAlign: 'center' },
  hiddenCodeInput: { position: 'absolute', width: 1, height: 1, opacity: 0 },
  verifiedText: { color: '#22C55E', fontSize: 13, fontWeight: '900', marginTop: 12 },
  connectedBanner: { minHeight: 82, borderRadius: 16, borderWidth: 1, borderColor: '#A7F3C2', backgroundColor: '#ECFDF3', flexDirection: 'row', alignItems: 'center', gap: 16, paddingHorizontal: 16, marginBottom: 16 },
  connectedIcon: { width: 44, height: 44, borderRadius: 22, alignItems: 'center', justifyContent: 'center', backgroundColor: '#22C55E' },
  connectedTitle: { color: '#0F8A47', fontSize: 17, fontWeight: '900' },
  connectedSub: { color: '#52647C', fontSize: 15, fontWeight: '600', marginTop: 3 },
  roleGrid: { flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'space-between', rowGap: 16, marginTop: 16 },
  roleCard: { width: '48%', minHeight: 250, borderRadius: 16, borderWidth: 1.3, borderColor: '#DCE5EF', backgroundColor: '#FFFFFF', padding: 14, alignItems: 'center', shadowColor: '#0F172A', shadowOpacity: 0.08, shadowOffset: { width: 0, height: 8 }, shadowRadius: 15, elevation: 3 },
  roleSelected: { borderColor: '#A78BFA', borderWidth: 2.2, backgroundColor: '#F7F1FF', shadowColor: '#8B5CF6', shadowOpacity: 0.34, shadowOffset: { width: 0, height: 9 }, shadowRadius: 10, elevation: 7 },
  roleCheck: { position: 'absolute', top: 20, right: 13, zIndex: 3, width: 30, height: 30, borderRadius: 15, alignItems: 'center', justifyContent: 'center', backgroundColor: '#A78BFA' },
  roleArt: { width: '100%', height: 88, borderRadius: 13, overflow: 'hidden', marginBottom: 12 },
  sceneGround: { position: 'absolute', left: 0, right: 0, bottom: 0, height: 20, backgroundColor: '#7EE1A8' },
  sceneTree: { position: 'absolute', width: 20, height: 34, borderRadius: 12, backgroundColor: '#86EFAC' },
  sceneSun: { position: 'absolute', width: 18, height: 18, borderRadius: 9, backgroundColor: '#FDE68A' },
  schoolBlock: { position: 'absolute', right: 6, bottom: 17, width: 34, height: 32, borderRadius: 4, backgroundColor: '#BFDBFE', alignItems: 'center', justifyContent: 'center' },
  schoolText: { color: '#2563EB', fontSize: 6, fontWeight: '900' },
  cityBlock: { position: 'absolute', bottom: 16, width: 24, borderRadius: 3, backgroundColor: '#CBD5E1' },
  bench: { position: 'absolute', left: 38, right: 34, bottom: 25, height: 12, borderRadius: 6, backgroundColor: '#B7791F' },
  sceneEmoji: { position: 'absolute', fontSize: 42, lineHeight: 46 },
  personFigure: { position: 'absolute', width: 32, height: 54, alignItems: 'center' },
  personHair: { position: 'absolute', top: 0, width: 21, height: 15, borderRadius: 10, backgroundColor: '#111827', zIndex: 1 },
  seniorHair: { backgroundColor: '#E5E7EB' },
  personHead: { width: 18, height: 18, borderRadius: 9, marginTop: 7, backgroundColor: '#A16207', zIndex: 2 },
  personBody: { width: 24, height: 24, borderRadius: 6, marginTop: -1 },
  personBag: { position: 'absolute', right: 0, top: 25, width: 8, height: 16, borderRadius: 3, backgroundColor: '#F97316' },
  personLegRow: { flexDirection: 'row', gap: 4, marginTop: 0 },
  personLeg: { width: 7, height: 14, borderRadius: 3 },
  personSkirtLeg: { height: 10 },
  roleTitle: { color: '#0F172A', fontSize: 18, lineHeight: 23, fontWeight: '900', textAlign: 'center' },
  roleTitleSelected: { color: '#A78BFA' },
  roleDesc: { color: '#425C7A', fontSize: 13, lineHeight: 18, fontWeight: '600', textAlign: 'center', marginTop: 9 },
  roleContinue: { width: '100%', minHeight: 70, borderRadius: 16, alignItems: 'center', justifyContent: 'center', marginTop: 10, backgroundColor: '#8B5CF6', overflow: 'hidden' },
  roleContinueGradient: { width: '100%', minHeight: 70, alignItems: 'center', justifyContent: 'center' },
  planCard: { borderRadius: 24, borderWidth: 1.4, borderColor: '#BAE6FD', backgroundColor: '#FFFFFF', padding: 22, gap: 16 },
  planTop: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start' },
  badge: { alignSelf: 'flex-start', overflow: 'hidden', color: '#FFFFFF', fontSize: 12, fontWeight: '900', paddingHorizontal: 12, paddingVertical: 7, borderRadius: 14, backgroundColor: '#22D3EE' },
  planName: { color: '#0F172A', fontSize: 18, fontWeight: '900', marginTop: 14 },
  price: { color: '#0F172A', fontSize: 34, fontWeight: '900', textAlign: 'right' },
  perMonth: { color: '#667085', fontSize: 13, fontWeight: '600', textAlign: 'right' },
  checkRow: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  checkText: { color: '#0F172A', fontSize: 15, fontWeight: '700' },
  privacyHeader: { marginHorizontal: -24, marginTop: 12, padding: 24, backgroundColor: '#071225' },
  privacyTitle: { color: '#FFFFFF', fontSize: 22, fontWeight: '900' },
  privacySub: { color: '#A8B3C7', fontSize: 14, fontWeight: '700', marginTop: 3 },
  privacyMatterTitle: { color: '#0F172A', fontSize: 22, fontWeight: '900', marginTop: 4 },
  privacyMatterSub: { color: '#667085', fontSize: 14, lineHeight: 21, fontWeight: '600' },
  dpdpCard: { minHeight: 68, borderRadius: 16, backgroundColor: '#EEF6FF', flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 16 },
  dpdpTitle: { color: '#0F172A', fontSize: 15, fontWeight: '900' },
  dpdpSub: { color: '#667085', fontSize: 12, fontWeight: '700', marginTop: 3 },
  privacyScreen: { marginHorizontal: -24, marginTop: -5, backgroundColor: '#F8FAFC' },
  privacyHero: { minHeight: 140, backgroundColor: '#152D4A', paddingHorizontal: 28, paddingTop: 54, justifyContent: 'center' },
  privacyBrandRow: { flexDirection: 'row', alignItems: 'center', gap: 14 },
  privacyHeroTitle: { color: '#FFFFFF', fontSize: 22, fontWeight: '900' },
  privacyHeroSub: { color: '#A8B6CC', fontSize: 15, fontWeight: '700', marginTop: 4 },
  privacyStepPill: { height: 32, borderRadius: 16, paddingHorizontal: 13, alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(255,255,255,0.12)' },
  privacyStepText: { color: '#D8E4F4', fontSize: 13, fontWeight: '800' },
  privacyBody: { paddingHorizontal: 24, paddingTop: 26, paddingBottom: 28 },
  privacyMainTitle: { color: '#0B1120', fontSize: 25, lineHeight: 31, fontWeight: '900' },
  privacyIntro: { color: '#52647C', fontSize: 17, lineHeight: 28, fontWeight: '600', marginTop: 10 },
  dpdpWideCard: { minHeight: 80, borderRadius: 17, borderWidth: 1.2, borderColor: '#B8DAFF', backgroundColor: '#EFF7FF', flexDirection: 'row', alignItems: 'center', gap: 16, paddingHorizontal: 17, marginTop: 26 },
  dpdpWideTitle: { color: '#3B82F6', fontSize: 17, fontWeight: '900' },
  dpdpWideSub: { color: '#52647C', fontSize: 14, fontWeight: '700', marginTop: 4 },
  privacySectionLabel: { color: '#64748B', fontSize: 13, fontWeight: '900', letterSpacing: 2, marginTop: 26, marginBottom: 12 },
  requiredConsentRow: { minHeight: 82, borderRadius: 17, borderWidth: 1.2, borderColor: '#93D0FF', backgroundColor: '#EFF8FF', flexDirection: 'row', alignItems: 'center', gap: 14, paddingHorizontal: 18, marginBottom: 12 },
  requiredCheck: { width: 30, height: 30, borderRadius: 15, alignItems: 'center', justifyContent: 'center', backgroundColor: '#22C55E' },
  requiredCopy: { flex: 1 },
  requiredConsentTitle: { color: '#0B1120', fontSize: 17, fontWeight: '900' },
  requiredSmall: { color: '#EF233C', fontSize: 12, fontWeight: '800', marginTop: 4 },
  privacyOptRow: { minHeight: 116, borderRadius: 17, borderWidth: 1, borderColor: '#D7E1EC', backgroundColor: '#F8FAFC', flexDirection: 'row', alignItems: 'flex-start', gap: 13, padding: 18, marginBottom: 12 },
  switchTrack: { width: 54, height: 30, borderRadius: 15, backgroundColor: '#E2E8F0', padding: 4 },
  switchTrackOn: { backgroundColor: '#22C55E' },
  switchKnob: { width: 22, height: 22, borderRadius: 11, backgroundColor: '#FFFFFF' },
  switchKnobOn: { marginLeft: 24 },
  privacyOptCopy: { flex: 1 },
  privacyOptTitle: { color: '#0B1120', fontSize: 17, fontWeight: '900' },
  privacyOptDesc: { color: '#52647C', fontSize: 14, lineHeight: 22, fontWeight: '600', marginTop: 8 },
  privacyHint: { color: '#93A2B7', fontSize: 15, lineHeight: 24, fontWeight: '700', textAlign: 'center', marginTop: 18 },
  skipOptional: { color: '#0084FF', fontSize: 17, fontWeight: '800', textAlign: 'center', textDecorationLine: 'underline', marginTop: 26, marginBottom: 16 },
  declineText: { color: '#94A3B8', fontSize: 16, fontWeight: '800', textAlign: 'center', paddingVertical: 18 },
  permissionTitleRow: { flexDirection: 'row', alignItems: 'center', gap: 18, marginTop: 4, marginBottom: 26 },
  permissionShield: { width: 68, height: 68, borderRadius: 21, alignItems: 'center', justifyContent: 'center', backgroundColor: '#14B8F3' },
  permissionIntro: { color: '#52647C', fontSize: 17, lineHeight: 26, fontWeight: '600', marginTop: 4 },
  permissionProgress: { minHeight: 74, borderRadius: 17, borderWidth: 1, borderColor: '#A7F3C2', backgroundColor: '#ECFDF3', paddingHorizontal: 18, justifyContent: 'center', marginBottom: 24 },
  permissionProgressTitle: { color: '#22C55E', fontSize: 15, fontWeight: '900', marginBottom: 6 },
  permissionProgressText: { color: '#52647C', fontSize: 15, fontWeight: '700' },
  permissionProgressCount: { color: '#16A34A', fontSize: 18, fontWeight: '900' },
  permissionCard: { minHeight: 142, borderRadius: 19, backgroundColor: '#FFFFFF', flexDirection: 'row', alignItems: 'flex-start', gap: 16, padding: 20, marginBottom: 14, shadowColor: '#0F172A', shadowOpacity: 0.05, shadowOffset: { width: 0, height: 8 }, shadowRadius: 18, elevation: 2 },
  permissionCopy: { flex: 1, minWidth: 0 },
  permissionCardTop: { flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: 8, marginBottom: 8 },
  permissionTitle: { color: '#0B1120', fontSize: 18, fontWeight: '900' },
  permissionBadge: { overflow: 'hidden', borderRadius: 13, paddingHorizontal: 10, paddingVertical: 5, fontSize: 12, fontWeight: '900' },
  permissionBadgeRequired: { color: '#EF4444', backgroundColor: '#FEE2E2' },
  permissionBadgeOptional: { color: '#F59E0B', backgroundColor: '#FFF7E5' },
  permissionBullet: { color: '#52647C', fontSize: 13, lineHeight: 22, fontWeight: '700' },
  permissionAction: { minWidth: 70, height: 40, borderRadius: 20, alignItems: 'center', justifyContent: 'center', backgroundColor: '#0EA5E9', paddingHorizontal: 14 },
  permissionActionDone: { backgroundColor: '#22C55E' },
  permissionActionSkip: { backgroundColor: '#F1F5F9' },
  permissionActionText: { color: '#FFFFFF', fontSize: 14, fontWeight: '900' },
  permissionActionSkipText: { color: '#64748B' },
  activateButton: { marginTop: 10, borderRadius: 18, shadowColor: '#0EA5E9', shadowOpacity: 0.2, shadowOffset: { width: 0, height: 14 }, shadowRadius: 24, elevation: 4 },
  activateGradient: { minHeight: 68, borderRadius: 18, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 9 },
  activateText: { color: '#FFFFFF', fontSize: 20, fontWeight: '900' },
  backConsentText: { color: '#94A3B8', fontSize: 16, fontWeight: '800', textAlign: 'center', paddingTop: 28, paddingBottom: 16 },
  consentRow: { minHeight: 82, borderRadius: 18, borderWidth: 1, borderColor: '#D6E4EE', backgroundColor: '#F8FAFC', flexDirection: 'row', alignItems: 'center', gap: 14, paddingHorizontal: 16 },
  toggle: { width: 36, height: 36, borderRadius: 18, alignItems: 'center', justifyContent: 'center', backgroundColor: '#E2E8F0' },
  toggleOn: { backgroundColor: '#22C55E' },
  consentCopy: { flex: 1 },
  consentTitle: { color: '#0F172A', fontSize: 16, fontWeight: '900' },
  required: { color: '#E11D48', fontSize: 12, fontWeight: '800', marginTop: 3 },
  consentDesc: { color: '#667085', fontSize: 13, lineHeight: 20, fontWeight: '600', marginTop: 6 },
  skipText: { color: '#64748B', textAlign: 'center', fontSize: 14, fontWeight: '800', marginVertical: 12 },
});
