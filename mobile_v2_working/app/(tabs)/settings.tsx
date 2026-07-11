import React, { useEffect, useState } from 'react';
import { KeyboardAvoidingView, Platform, ScrollView, StyleSheet, Switch, Text, TextInput, TouchableOpacity, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { LinearGradient } from 'expo-linear-gradient';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { useAuthStore } from '@/stores/authStore';

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
      ['call-outline', '#EF4444', 'Manage Contacts', '4 contacts - SOS order'],
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
      ['location-outline', '#0EA5E9', 'Location History', 'View all tracked locations'],
      ['navigate-outline', '#22C55E', 'Route History', 'Journey playback'],
      ['notifications-outline', '#F59E0B', 'Alert History', 'All alerts & notifications'],
      ['warning-outline', '#EF4444', 'SOS History', 'Past emergency events'],
      ['location-outline', '#22C55E', 'Safe Walk History', 'Monitored walk sessions'],
      ['people-outline', '#0EA5E9', 'Family Activity Log', 'Circle events & changes'],
    ],
  },
  {
    title: 'HELP & SUPPORT',
    items: [
      ['help-circle-outline', '#0EA5E9', 'FAQ', 'Common questions'],
      ['chatbubble-outline', '#22C55E', 'Contact Support', 'Chat with our team'],
      ['alert-outline', '#F59E0B', 'Report Issue', 'App bugs or safety concerns'],
    ],
  },
] as const;

type EmergencyContact = {
  id: string;
  rank: number;
  color: string;
  avatar: string;
  name: string;
  role: string;
  phone: string;
  locked?: boolean;
  draftName?: string;
  draftPhone?: string;
};

const emergencyContactTypeMeta: Record<string, { avatar: string; color: string }> = {
  Doctor: { avatar: '\uD83D\uDC68\u200D\u2695\uFE0F', color: '#0B8FF0' },
  Relative: { avatar: '\uD83D\uDC74', color: '#F59E0B' },
  Neighbor: { avatar: '\uD83C\uDFE0', color: '#EF4444' },
  Teacher: { avatar: '\uD83E\uDDD1\u200D\uD83C\uDFEB', color: '#22C55E' },
  'Building Security': { avatar: '\uD83D\uDEE1\uFE0F', color: '#8B5CF6' },
  'Family Friend': { avatar: '\uD83D\uDC64', color: '#EC4899' },
};

const initialEmergencyContacts: EmergencyContact[] = [
  { id: 'parent', rank: 1, color: '#0B8FF0', avatar: '\uD83D\uDC68', name: 'Rajesh Sharma', role: 'Parent (Primary Guardian)', phone: '+91 98765 43210', locked: true },
  { id: 'coparent', rank: 2, color: '#22C55E', avatar: '\uD83D\uDC69', name: 'Sunita Sharma', role: 'Co-Parent', phone: '+91 98765 43211', locked: true },
  { id: 'doctor', rank: 3, color: '#8B5CF6', avatar: '\uD83D\uDC68\u200D\u2695\uFE0F', name: 'Dr. Ramesh Mehta', role: 'Doctor', phone: '+91 98765 43212' },
  { id: 'relative', rank: 4, color: '#F59E0B', avatar: '\uD83D\uDC74', name: 'Uncle Suresh', role: 'Relative', phone: '+91 98765 43213' },
  { id: 'neighbor', rank: 5, color: '#EF4444', avatar: '\uD83C\uDFE0', name: 'Mr. Sharma', role: 'Neighbor', phone: '+91 98765 43214' },
  { id: 'friend', rank: 6, color: '#EC4899', avatar: '\uD83D\uDC64', name: 'Rahul Gupta', role: 'Family Friend', phone: '+91 98765 43215' },
];

export default function SettingsScreen() {
  const router = useRouter();
  const { logout, profileMode } = useAuthStore();
  const [showSubscription, setShowSubscription] = useState(false);
  const [showProfile, setShowProfile] = useState(false);
  const [showFamilyCircle, setShowFamilyCircle] = useState(false);
  const [showEmergencyContacts, setShowEmergencyContacts] = useState(false);
  const [showActivityHistory, setShowActivityHistory] = useState(false);
  const [sheet, setSheet] = useState<null | 'member' | 'invoices' | 'cancel' | 'coparent' | 'transfer' | 'emergencyContact'>(null);
  const [emergencyContacts, setEmergencyContacts] = useState<EmergencyContact[]>(initialEmergencyContacts);
  const [editingEmergencyId, setEditingEmergencyId] = useState<string | null>(null);

  const addEmergencyContact = (contactType: string) => {
    const meta = emergencyContactTypeMeta[contactType] ?? emergencyContactTypeMeta.Relative;
    const id = `new-${Date.now()}`;
    const name = `New ${contactType}`;
    setEmergencyContacts((current) => [
      ...current,
      {
        id,
        rank: current.length + 1,
        color: meta.color,
        avatar: meta.avatar,
        name,
        role: contactType,
        phone: '+91 00000 00000',
        draftName: name,
        draftPhone: '+91 00000 00000',
      },
    ]);
    setEditingEmergencyId(id);
    setSheet(null);
    setShowEmergencyContacts(true);
  };

  const updateEmergencyDraft = (id: string, field: 'draftName' | 'draftPhone', value: string) => {
    setEmergencyContacts((current) => current.map((contact) => (contact.id === id ? { ...contact, [field]: value } : contact)));
  };

  const editEmergencyContact = (id: string) => {
    setEmergencyContacts((current) => current.map((contact) => (
      contact.id === id ? { ...contact, draftName: contact.name, draftPhone: contact.phone } : contact
    )));
    setEditingEmergencyId(id);
  };

  const saveEmergencyContact = (id: string) => {
    setEmergencyContacts((current) => current.map((contact) => (
      contact.id === id
        ? { ...contact, name: contact.draftName?.trim() || contact.name, phone: contact.draftPhone?.trim() || contact.phone }
        : contact
    )));
    setEditingEmergencyId(null);
  };

  const cancelEmergencyEdit = (id: string) => {
    setEmergencyContacts((current) => {
      const target = current.find((contact) => contact.id === id);
      const next = target?.id.startsWith('new-') ? current.filter((contact) => contact.id !== id) : current;
      return next.map((contact, index) => ({ ...contact, rank: index + 1 }));
    });
    setEditingEmergencyId(null);
  };

  const handleSignOut = async () => {
    await logout();
    router.replace('/intro');
  };

  if (profileMode === 'women' || profileMode === 'senior') {
    return <WomanSettingsScreen />;
  }

  if (['kids', 'family'].includes(profileMode)) {
    return <ChildSettingsScreen />;
  }

  if (showSubscription) {
    return (
      <View style={styles.safe}>
        <ParentSubscriptionScreen
          onBack={() => setShowSubscription(false)}
          onAddMember={() => setSheet('member')}
          onInvoices={() => setSheet('invoices')}
          onCancel={() => setSheet('cancel')}
          onCoParent={() => setSheet('coparent')}
          onTransfer={() => setSheet('transfer')}
        />
        <ParentSettingsSheet type={sheet} onClose={() => setSheet(null)} />
      </View>
    );
  }

  if (showProfile) {
    return <ParentProfileScreen onBack={() => setShowProfile(false)} />;
  }

  if (showFamilyCircle) {
    return (
      <View style={styles.safe}>
        <ParentFamilyCircleScreen onBack={() => setShowFamilyCircle(false)} onReplaceCoParent={() => setSheet('coparent')} />
        <ParentSettingsSheet type={sheet} onClose={() => setSheet(null)} />
      </View>
    );
  }

  if (showEmergencyContacts) {
    return (
      <View style={styles.safe}>
        <ParentEmergencyContactsScreen
          contacts={emergencyContacts}
          editingContactId={editingEmergencyId}
          onBack={() => setShowEmergencyContacts(false)}
          onAdd={() => setSheet('emergencyContact')}
          onEdit={editEmergencyContact}
          onChangeDraft={updateEmergencyDraft}
          onSaveEdit={saveEmergencyContact}
          onCancelEdit={cancelEmergencyEdit}
        />
        <ParentSettingsSheet type={sheet} onClose={() => setSheet(null)} onAddEmergencyContact={addEmergencyContact} />
      </View>
    );
  }

  if (showActivityHistory) {
    return <ParentActivityHistoryScreen onBack={() => setShowActivityHistory(false)} />;
  }

  return (
    <SafeAreaView style={styles.safe} edges={['top']}>
      <ScrollView style={styles.scroll} contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
        <View style={styles.hero}>
          <View style={styles.heroRow}>
            <View style={styles.brandRow}>
              <View style={styles.avatarCircle}>
                <Text style={styles.avatarEmoji}>👨</Text>
              </View>
              <View>
                <Text style={styles.personName}>Rajesh Sharma</Text>
                <Text style={styles.personMeta}>Primary Guardian - Premium</Text>
              </View>
            </View>
            <Ionicons name="shield-checkmark" size={28} color="#16C7C7" />
          </View>
        </View>

        <LinearGradient colors={['#11B6F4', '#26E36E']} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={styles.planCard}>
          <View>
            <Text style={styles.planLabel}>ACTIVE PLAN</Text>
            <Text style={styles.planName}>Premium Family Circle</Text>
            <Text style={styles.planMeta}>1 Parent - 1 Co-Parent - 1 Member</Text>
          </View>
          <View style={styles.priceWrap}>
            <Text style={styles.price}>₹299</Text>
            <Text style={styles.perMonth}>/month</Text>
          </View>
          <View style={styles.planButtons}>
            <TouchableOpacity style={styles.manageBtn} activeOpacity={0.85} onPress={() => setShowSubscription(true)}>
              <Text style={styles.manageText}>Manage Plan</Text>
            </TouchableOpacity>
            <TouchableOpacity style={styles.addBtn} activeOpacity={0.85} onPress={() => setShowSubscription(true)}>
              <Text style={styles.addText}>+ Add Member</Text>
            </TouchableOpacity>
          </View>
        </LinearGradient>

        {sections.map((section) => (
          <View key={section.title} style={styles.section}>
            <Text style={styles.sectionTitle}>{section.title}</Text>
            <View style={styles.card}>
              {section.items.map(([icon, color, title, subtitle], index) => (
                <TouchableOpacity
                  key={title}
                  activeOpacity={0.78}
                  onPress={() => {
                    if (title === 'Profile') setShowProfile(true);
                    if (title === 'Family Circle') setShowFamilyCircle(true);
                    if (title === 'Subscription') setShowSubscription(true);
                    if (title === 'Billing & Invoices') setSheet('invoices');
                    if (title === 'Manage Contacts') setShowEmergencyContacts(true);
                    if (title === 'Location History') setShowActivityHistory(true);
                    if (title === 'Route History') setShowActivityHistory(true);
                    if (title === 'Alert History') setShowActivityHistory(true);
                    if (title === 'SOS History') setShowActivityHistory(true);
                    if (title === 'Safe Walk History') setShowActivityHistory(true);
                    if (title === 'Family Activity Log') setShowActivityHistory(true);
                  }}
                  style={[styles.row, index > 0 && styles.rowBorder]}
                >
                  <View style={[styles.rowIcon, { backgroundColor: `${color}14` }]}>
                    <Ionicons name={icon as keyof typeof Ionicons.glyphMap} size={18} color={color} />
                  </View>
                  <View style={styles.rowCopy}>
                    <Text style={styles.rowTitle}>{title}</Text>
                    <Text style={styles.rowSub}>{subtitle}</Text>
                  </View>
                  <Ionicons name="chevron-forward" size={18} color="#CBD5E1" />
                </TouchableOpacity>
              ))}
            </View>
          </View>
        ))}

        <TouchableOpacity activeOpacity={0.84} style={styles.signOutBtn} onPress={handleSignOut}>
          <Ionicons name="log-out-outline" size={20} color="#EF4444" />
          <Text style={styles.signOutText}>Sign Out</Text>
        </TouchableOpacity>
        <Text style={styles.versionText}>NISCHINT v1.0.0 - Guardian Dashboard</Text>
      </ScrollView>
      <ParentSettingsSheet type={sheet} onClose={() => setSheet(null)} onAddEmergencyContact={addEmergencyContact} />
    </SafeAreaView>
  );
}

function ParentProfileScreen({ onBack }: { onBack: () => void }) {
  return (
    <SafeAreaView style={profileStyles.safe} edges={['top']}>
      <View style={profileStyles.header}>
        <TouchableOpacity activeOpacity={0.82} onPress={onBack} style={profileStyles.backBtn}>
          <Ionicons name="chevron-back" size={25} color="#0F172A" />
        </TouchableOpacity>
        <Text style={profileStyles.headerTitle}>Profile</Text>
      </View>
      <ScrollView style={profileStyles.scroll} contentContainerStyle={profileStyles.content} showsVerticalScrollIndicator={false}>
        <View style={profileStyles.heroCard}>
          <LinearGradient colors={['#0B91FF', '#24D38B']} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={profileStyles.avatar}>
            <Text style={profileStyles.avatarLetter}>R</Text>
          </LinearGradient>
          <Text style={profileStyles.name}>Rajesh Sharma</Text>
          <Text style={profileStyles.role}>Primary Guardian - Premium</Text>
          <TouchableOpacity activeOpacity={0.82} style={profileStyles.photoBtn}>
            <Text style={profileStyles.photoBtnText}>Change Photo</Text>
          </TouchableOpacity>
        </View>

        <ProfileInfoCard label="FULL NAME" value="Rajesh Sharma" />
        <ProfileInfoCard label="PHONE" value="+91 98765 43210" />
        <ProfileInfoCard label="EMAIL" value="rajesh@gmail.com" />
        <ProfileInfoCard label="DATE OF BIRTH" value="15 March 1982" />

        <TouchableOpacity activeOpacity={0.86} style={profileStyles.saveBtn}>
          <Text style={profileStyles.saveText}>Save Changes</Text>
        </TouchableOpacity>
      </ScrollView>
    </SafeAreaView>
  );
}

function ProfileInfoCard({ label, value }: { label: string; value: string }) {
  return (
    <View style={profileStyles.infoCard}>
      <Text style={profileStyles.infoLabel}>{label}</Text>
      <Text style={profileStyles.infoValue}>{value}</Text>
    </View>
  );
}

function ParentFamilyCircleScreen({ onBack, onReplaceCoParent }: { onBack: () => void; onReplaceCoParent: () => void }) {
  const [invitePanel, setInvitePanel] = useState<null | 'qr' | 'code' | 'history'>(null);
  const [inviteSeconds, setInviteSeconds] = useState(15 * 60);
  const inviteCode = 'N4H7K2';
  const isInviteActive = invitePanel === 'qr' || invitePanel === 'code';

  useEffect(() => {
    if (!isInviteActive) return;
    setInviteSeconds(15 * 60);
    const timer = setInterval(() => {
      setInviteSeconds((seconds) => Math.max(0, seconds - 1));
    }, 1000);
    return () => clearInterval(timer);
  }, [isInviteActive, invitePanel]);

  return (
    <SafeAreaView style={familyCircleStyles.safe} edges={['top']}>
      <View style={familyCircleStyles.header}>
        <TouchableOpacity activeOpacity={0.82} onPress={onBack} style={familyCircleStyles.backBtn}>
          <Ionicons name="chevron-back" size={25} color="#0F172A" />
        </TouchableOpacity>
        <Text style={familyCircleStyles.headerTitle}>Family Circle</Text>
      </View>
      <ScrollView style={familyCircleStyles.scroll} contentContainerStyle={familyCircleStyles.content} showsVerticalScrollIndicator={false}>
        <Text style={familyCircleStyles.sectionLabel}>CIRCLE MEMBERS</Text>
        <View style={familyCircleStyles.card}>
          <CircleMember emoji="👨" name="Rajesh Sharma" role="Primary Parent" badge="You" />
          <CircleMember emoji="👩" name="Sunita Sharma" role="Co-Parent - Monitoring access only" bordered />
          <CircleMember emoji="👧" name="Priya Sharma" role="Protected Member" badge="Child" bordered purple />
        </View>

        <Text style={familyCircleStyles.sectionLabel}>INVITE & LINK</Text>
        <View style={familyCircleStyles.card}>
          <FamilyCircleRow icon="qr-code-outline" color="#0EA5E9" title="Generate QR Code" subtitle="Share with new member - active 15 min" onPress={() => setInvitePanel('qr')} />
          <FamilyCircleRow icon="key-outline" color="#22C55E" title="Invite Code" subtitle="6-character code - active 15 min" bordered onPress={() => setInvitePanel('code')} />
          <FamilyCircleRow icon="time-outline" color="#64748B" title="Invite History" subtitle="Past invitations" bordered onPress={() => setInvitePanel('history')} />
        </View>

        <Text style={familyCircleStyles.sectionLabel}>DANGER ZONE</Text>
        <View style={familyCircleStyles.card}>
          <FamilyCircleRow icon="person-add-outline" color="#F59E0B" title="Replace Co-Parent" subtitle="Remove & invite new" onPress={onReplaceCoParent} />
          <FamilyCircleRow icon="trash-outline" color="#EF4444" title="Remove Protected Member" subtitle="Requires OTP confirmation" bordered danger />
        </View>
      </ScrollView>
      {invitePanel ? (
        <ParentInvitePanel
          mode={invitePanel}
          inviteCode={inviteCode}
          seconds={inviteSeconds}
          onModeChange={(mode: 'qr' | 'code') => setInvitePanel(mode)}
          onClose={() => setInvitePanel(null)}
        />
      ) : null}
    </SafeAreaView>
  );
}

function ParentInvitePanel({
  mode,
  inviteCode,
  seconds,
  onModeChange,
  onClose,
}: {
  mode: 'qr' | 'code' | 'history';
  inviteCode: string;
  seconds: number;
  onModeChange: (mode: 'qr' | 'code') => void;
  onClose: () => void;
}) {
  const minutes = Math.floor(seconds / 60).toString().padStart(2, '0');
  const secs = (seconds % 60).toString().padStart(2, '0');

  return (
    <View style={familyCircleStyles.inviteLayer}>
      <TouchableOpacity activeOpacity={1} style={familyCircleStyles.inviteBackdrop} onPress={onClose} />
      <View style={familyCircleStyles.inviteSheet}>
        <View style={familyCircleStyles.sheetHandle} />
        <View style={familyCircleStyles.inviteHead}>
          <View>
            <Text style={familyCircleStyles.inviteTitle}>{mode === 'history' ? 'Invite History' : 'Share Family Circle Invite'}</Text>
            <Text style={familyCircleStyles.inviteSub}>{mode === 'history' ? 'Recent QR and invite code activity' : 'Active for 15 minutes'}</Text>
          </View>
          <TouchableOpacity activeOpacity={0.82} onPress={onClose} style={familyCircleStyles.inviteClose}>
            <Ionicons name="close" size={23} color="#64748B" />
          </TouchableOpacity>
        </View>

        {mode === 'history' ? (
          <View style={familyCircleStyles.historyList}>
            {[
              ['QR Code', 'Shared with Priya - Used', 'Jun 5, 08:40 AM'],
              ['Invite Code', 'Shared with Sunita - Used', 'Jun 5, 08:28 AM'],
              ['QR Code', 'Expired after 15 min', 'Jun 4, 07:10 PM'],
            ].map(([title, sub, time]) => (
              <View key={`${title}-${time}`} style={familyCircleStyles.historyRow}>
                <View style={familyCircleStyles.historyIcon}>
                  <Ionicons name={title === 'QR Code' ? 'qr-code-outline' : 'key-outline'} size={20} color="#0B84FF" />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={familyCircleStyles.historyTitle}>{title}</Text>
                  <Text style={familyCircleStyles.historySub}>{sub}</Text>
                </View>
                <Text style={familyCircleStyles.historyTime}>{time}</Text>
              </View>
            ))}
          </View>
        ) : (
          <>
            <View style={familyCircleStyles.inviteTabs}>
              <TouchableOpacity activeOpacity={0.82} onPress={() => onModeChange('qr')} style={[familyCircleStyles.inviteTab, mode === 'qr' && familyCircleStyles.inviteTabActive]}>
                <Text style={[familyCircleStyles.inviteTabText, mode === 'qr' && familyCircleStyles.inviteTabTextActive]}>QR Code</Text>
              </TouchableOpacity>
              <TouchableOpacity activeOpacity={0.82} onPress={() => onModeChange('code')} style={[familyCircleStyles.inviteTab, mode === 'code' && familyCircleStyles.inviteTabActive]}>
                <Text style={[familyCircleStyles.inviteTabText, mode === 'code' && familyCircleStyles.inviteTabTextActive]}>Invite Code</Text>
              </TouchableOpacity>
            </View>

            <View style={familyCircleStyles.timerPill}>
              <Ionicons name="time-outline" size={18} color="#0B84FF" />
              <Text style={familyCircleStyles.timerText}>Active for {minutes}:{secs}</Text>
            </View>

            {mode === 'qr' ? (
              <View style={familyCircleStyles.qrWrap}>
                <FakeQrCode />
                <Text style={familyCircleStyles.qrCaption}>Ask the member to scan this QR from their NISCHINT app.</Text>
              </View>
            ) : (
              <View style={familyCircleStyles.codeWrap}>
                <Text style={familyCircleStyles.codeLabel}>6-character invite code</Text>
                <View style={familyCircleStyles.codeBoxes}>
                  {inviteCode.split('').map((char) => (
                    <View key={char} style={familyCircleStyles.codeBox}>
                      <Text style={familyCircleStyles.codeChar}>{char}</Text>
                    </View>
                  ))}
                </View>
                <Text style={familyCircleStyles.qrCaption}>Share this code with a child, woman, senior, family member, or co-parent.</Text>
              </View>
            )}

            <View style={familyCircleStyles.allowedBox}>
              <Ionicons name="shield-checkmark-outline" size={20} color="#16A34A" />
              <Text style={familyCircleStyles.allowedText}>Can join: Child, Woman, Senior, Family Member, Co-Parent</Text>
            </View>
            <TouchableOpacity activeOpacity={0.86} style={familyCircleStyles.shareInviteBtn}>
              <Ionicons name="share-social-outline" size={21} color="#FFFFFF" />
              <Text style={familyCircleStyles.shareInviteText}>{mode === 'qr' ? 'Share QR Invite' : 'Share Invite Code'}</Text>
            </TouchableOpacity>
          </>
        )}
      </View>
    </View>
  );
}

function FakeQrCode() {
  const filled = new Set([0, 1, 2, 4, 6, 7, 8, 10, 13, 15, 16, 18, 20, 21, 23, 26, 27, 28, 31, 33, 34, 36, 39, 40, 42, 45, 46, 47, 49, 51, 52, 54, 56, 59, 60, 62, 63]);
  return (
    <View style={familyCircleStyles.qrBox}>
      <View style={[familyCircleStyles.qrCorner, familyCircleStyles.qrCornerTopLeft]} />
      <View style={[familyCircleStyles.qrCorner, familyCircleStyles.qrCornerTopRight]} />
      <View style={[familyCircleStyles.qrCorner, familyCircleStyles.qrCornerBottomLeft]} />
      <View style={familyCircleStyles.qrGrid}>
        {Array.from({ length: 64 }).map((_, index) => (
          <View key={index} style={[familyCircleStyles.qrCell, filled.has(index) && familyCircleStyles.qrCellFilled]} />
        ))}
      </View>
    </View>
  );
}

function CircleMember({ emoji, name, role, badge, bordered, purple }: any) {
  return (
    <View style={[familyCircleStyles.memberRow, bordered && familyCircleStyles.rowBorder]}>
      <View style={[familyCircleStyles.memberAvatar, purple && familyCircleStyles.memberAvatarPurple]}>
        <Text style={familyCircleStyles.memberEmoji}>{emoji}</Text>
      </View>
      <View style={{ flex: 1 }}>
        <Text style={familyCircleStyles.memberName}>{name}</Text>
        <Text style={familyCircleStyles.memberRole}>{role}</Text>
      </View>
      {badge ? <Text style={[familyCircleStyles.memberBadge, purple && familyCircleStyles.memberBadgePurple]}>{badge}</Text> : null}
    </View>
  );
}

function FamilyCircleRow({ icon, color, title, subtitle, bordered, danger, onPress }: any) {
  return (
    <TouchableOpacity activeOpacity={0.78} onPress={onPress} style={[familyCircleStyles.actionRow, bordered && familyCircleStyles.rowBorder]}>
      <View style={[familyCircleStyles.actionIcon, { backgroundColor: `${color}14` }]}>
        <Ionicons name={icon as keyof typeof Ionicons.glyphMap} size={22} color={color} />
      </View>
      <View style={{ flex: 1 }}>
        <Text style={[familyCircleStyles.actionTitle, danger && familyCircleStyles.dangerText]}>{title}</Text>
        <Text style={familyCircleStyles.actionSub}>{subtitle}</Text>
      </View>
      <Ionicons name="chevron-forward" size={18} color="#CBD5E1" />
    </TouchableOpacity>
  );
}

function ParentEmergencyContactsScreen({ onBack, onAdd, contacts: liveContacts, editingContactId, onEdit, onChangeDraft, onSaveEdit, onCancelEdit }: any) {
  const contacts = [
    { rank: 1, color: '#0B8FF0', avatar: '👨', name: 'Rajesh Sharma', role: 'Parent (Primary Guardian)', phone: '+91 98765 43210', locked: true },
    { rank: 2, color: '#22C55E', avatar: '👩', name: 'Sunita Sharma', role: 'Co-Parent', phone: '+91 98765 43211', locked: true },
    { rank: 3, color: '#8B5CF6', avatar: '👨‍⚕️', name: 'Dr. Ramesh Mehta', role: 'Doctor', phone: '+91 98765 43212' },
    { rank: 4, color: '#F59E0B', avatar: '👴', name: 'Uncle Suresh', role: 'Relative', phone: '+91 98765 43213' },
    { rank: 5, color: '#EF4444', avatar: '🏠', name: 'Mr. Sharma', role: 'Neighbor', phone: '+91 98765 43214' },
    { rank: 6, color: '#EC4899', avatar: '👤', name: 'Rahul Gupta', role: 'Family Friend', phone: '+91 98765 43215' },
  ];
  const list = liveContacts ?? contacts;

  return (
    <SafeAreaView style={emergencyStyles.safe} edges={['top']}>
      <View style={emergencyStyles.hero}>
        <TouchableOpacity activeOpacity={0.82} onPress={onBack} style={emergencyStyles.backBtn}>
          <Ionicons name="arrow-back" size={26} color="#FFFFFF" />
        </TouchableOpacity>
        <View style={emergencyStyles.heroCopy}>
          <Text style={emergencyStyles.eyebrow}>SAFETY NETWORK</Text>
          <Text style={emergencyStyles.title}>Emergency Contacts</Text>
        </View>
        <TouchableOpacity activeOpacity={0.86} onPress={onAdd} style={emergencyStyles.addTopBtn}>
          <Ionicons name="add" size={22} color="#FFFFFF" />
          <Text style={emergencyStyles.addTopText}>Add</Text>
        </TouchableOpacity>
      </View>

      <ScrollView style={emergencyStyles.scroll} contentContainerStyle={emergencyStyles.content} showsVerticalScrollIndicator={false}>
        <View style={emergencyStyles.notice}>
          <Ionicons name="warning" size={22} color="#F59E0B" />
          <Text style={emergencyStyles.noticeText}>Contacts are alerted in order if SOS is not acknowledged by guardian within <Text style={emergencyStyles.noticeBold}>2 minutes</Text></Text>
        </View>

        {list.map((contact: EmergencyContact, index: number) => {
          const isEditing = editingContactId === contact.id;
          return (
          <View key={contact.id ?? contact.phone}>
            <View style={[emergencyStyles.contactCard, isEditing && emergencyStyles.contactCardEditing]}>
              <View style={emergencyStyles.contactTopRow}>
              <View style={[emergencyStyles.rankCircle, { backgroundColor: contact.color }]}>
                <Text style={emergencyStyles.rankText}>{contact.rank}</Text>
              </View>
              <View style={emergencyStyles.contactAvatar}>
                <Text style={emergencyStyles.contactEmoji}>{contact.avatar}</Text>
              </View>
              <View style={emergencyStyles.contactCopy}>
                <View style={emergencyStyles.nameRow}>
                  <Text style={emergencyStyles.contactName}>{contact.name}</Text>
                  {contact.locked ? (
                    <Text style={emergencyStyles.lockedPill}>
                      <Ionicons name="lock-closed-outline" size={10} color="#2563EB" /> Locked
                    </Text>
                  ) : null}
                </View>
                <Text style={emergencyStyles.contactRole}>{contact.role}</Text>
                <Text style={emergencyStyles.contactPhone}>{contact.phone}</Text>
              </View>
              <View style={emergencyStyles.contactActions}>
                <TouchableOpacity activeOpacity={0.82} style={emergencyStyles.callBtn}>
                  <Ionicons name="call-outline" size={22} color="#22C55E" />
                </TouchableOpacity>
                {!contact.locked ? (
                  <View style={emergencyStyles.smallActions}>
                    <TouchableOpacity activeOpacity={0.82} onPress={() => onEdit?.(contact.id)} style={emergencyStyles.editBtn}>
                      <Ionicons name="pencil-outline" size={20} color="#0B84FF" />
                    </TouchableOpacity>
                    <TouchableOpacity activeOpacity={0.82} style={emergencyStyles.deleteBtn}>
                      <Ionicons name="trash-outline" size={20} color="#EF4444" />
                    </TouchableOpacity>
                  </View>
                ) : null}
              </View>
              </View>
              {isEditing ? (
                <View style={emergencyStyles.editForm}>
                  <TextInput
                    value={contact.draftName ?? contact.name}
                    onChangeText={(value) => onChangeDraft?.(contact.id, 'draftName', value)}
                    placeholder="New Teacher"
                    placeholderTextColor="#94A3B8"
                    style={emergencyStyles.editInput}
                  />
                  <TextInput
                    value={contact.draftPhone ?? contact.phone}
                    onChangeText={(value) => onChangeDraft?.(contact.id, 'draftPhone', value)}
                    placeholder="+91 00000 00000"
                    placeholderTextColor="#94A3B8"
                    keyboardType="phone-pad"
                    style={emergencyStyles.editInput}
                  />
                  <View style={emergencyStyles.editButtons}>
                    <TouchableOpacity activeOpacity={0.86} onPress={() => onSaveEdit?.(contact.id)} style={emergencyStyles.saveBtn}>
                      <Text style={emergencyStyles.saveText}>Save</Text>
                    </TouchableOpacity>
                    <TouchableOpacity activeOpacity={0.86} onPress={() => onCancelEdit?.(contact.id)} style={emergencyStyles.cancelEditBtn}>
                      <Text style={emergencyStyles.cancelEditText}>Cancel</Text>
                    </TouchableOpacity>
                  </View>
                </View>
              ) : null}
            </View>
            {index < list.length - 1 ? (
              <View style={emergencyStyles.chainWrap}>
                <View style={[emergencyStyles.chainLine, { backgroundColor: `${list[index + 1].color}55` }]} />
                <Ionicons name="chevron-down" size={16} color={`${list[index + 1].color}99`} />
              </View>
            ) : null}
          </View>
          );
        })}

        <TouchableOpacity activeOpacity={0.86} onPress={onAdd} style={emergencyStyles.addCard}>
          <Ionicons name="person-add-outline" size={30} color="#0B84FF" />
          <Text style={emergencyStyles.addCardTitle}>Add Emergency Contact</Text>
          <Text style={emergencyStyles.addCardSub}>Tap to expand escalation chain</Text>
        </TouchableOpacity>
      </ScrollView>
    </SafeAreaView>
  );
}

function ParentActivityHistoryScreen({ onBack }: { onBack: () => void }) {
  const [tab, setTab] = useState('Location');
  const [range, setRange] = useState('Today');
  const topTabs = [
    ['Location', 'location-outline'],
    ['Routes', 'navigate-outline'],
    ['Alerts', 'notifications-outline'],
    ['SOS', 'warning-outline'],
    ['Safe Walk', 'walk-outline'],
    ['Permissions', 'shield-outline'],
    ['Devices', 'phone-portrait-outline'],
    ['Family', 'people-outline'],
  ];

  return (
    <SafeAreaView style={historyStyles.safe} edges={['top']}>
      <View style={historyStyles.header}>
        <TouchableOpacity activeOpacity={0.82} onPress={onBack} style={historyStyles.backBtn}>
          <Ionicons name="arrow-back" size={24} color="#0F172A" />
        </TouchableOpacity>
        <Text style={historyStyles.headerTitle}>Activity History</Text>
        <View style={historyStyles.personPill}>
          <Text style={historyStyles.personPillText}>👧 Priya</Text>
        </View>
        <TouchableOpacity activeOpacity={0.82} style={historyStyles.downloadBtn}>
          <Ionicons name="download-outline" size={20} color="#64748B" />
        </TouchableOpacity>
      </View>

      <View style={historyStyles.tabBar}>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={historyStyles.tabContent}>
          {topTabs.map(([label, icon]) => (
            <TouchableOpacity key={label} activeOpacity={0.84} onPress={() => setTab(label)} style={[historyStyles.tabPill, tab === label && historyStyles.tabPillActive]}>
              <Ionicons name={icon as keyof typeof Ionicons.glyphMap} size={15} color={tab === label ? '#FFFFFF' : '#64748B'} />
              <Text style={[historyStyles.tabText, tab === label && historyStyles.tabTextActive]}>{label}</Text>
            </TouchableOpacity>
          ))}
        </ScrollView>
      </View>

      <ScrollView style={historyStyles.scroll} contentContainerStyle={historyStyles.content} showsVerticalScrollIndicator={false}>
        {tab === 'Location' ? (
          <>
            <View style={historyStyles.rangeRow}>
              {['Today', 'Yesterday', '7 Days', '30 Days'].map((item) => (
                <TouchableOpacity key={item} activeOpacity={0.84} onPress={() => setRange(item)} style={[historyStyles.rangePill, range === item && historyStyles.rangePillActive]}>
                  <Text style={[historyStyles.rangeText, range === item && historyStyles.rangeTextActive]}>{item}</Text>
                </TouchableOpacity>
              ))}
            </View>
            <View style={historyStyles.summaryCard}>
              <HistoryStat label="Locations" value="5" blue />
              <HistoryStat label="Distance" value="14.2 km" />
              <HistoryStat label="Tracked" value="8.4 hrs" green />
            </View>
            <Text style={historyStyles.sectionLabel}>TODAY</Text>
            <View style={historyStyles.timeline}>
              <HistoryTimelineItem color="#F59E0B" title="Left Home" meta="8:10 AM  ·  12 Rajpur Colony, Noida" />
              <HistoryTimelineItem color="#22C55E" title="Arrived at School" meta="8:42 AM  ·  Delhi Public School, Sec 30" pill="32 min" />
              <View style={historyStyles.durationPill}><Text style={historyStyles.durationText}>4 hrs 20 min at School</Text></View>
              <HistoryTimelineItem color="#F59E0B" title="Left School" meta="2:35 PM  ·  Delhi Public School, Sec 30" />
              <HistoryTimelineItem color="#22C55E" title="Arrived Home" meta="3:05 PM  ·  12 Rajpur Colony, Noida" pill="30 min" />
            </View>
          </>
        ) : null}

        {tab === 'Routes' ? <HistoryRouteList /> : null}
        {tab === 'SOS' ? <HistorySosCard /> : null}
        {tab === 'Safe Walk' ? <HistorySafeWalkList /> : null}
        {tab === 'Permissions' ? <HistoryEventList type="permissions" /> : null}
        {tab === 'Devices' ? <HistoryEventList type="devices" /> : null}
        {tab === 'Family' ? <HistoryEventList type="family" /> : null}
        {tab === 'Alerts' ? <HistoryEventList type="alerts" /> : null}
      </ScrollView>
    </SafeAreaView>
  );
}

function HistoryStat({ label, value, blue, green }: any) {
  return (
    <View style={historyStyles.statBlock}>
      <Text style={historyStyles.statLabel}>{label}</Text>
      <Text style={[historyStyles.statValue, blue && historyStyles.blueText, green && historyStyles.greenText]}>{value}</Text>
    </View>
  );
}

function HistoryTimelineItem({ color, title, meta, pill }: any) {
  return (
    <View style={historyStyles.timelineRow}>
      <View style={[historyStyles.timelineDot, { borderColor: color }]} />
      <View style={historyStyles.timelineCard}>
        <View style={historyStyles.historyTitleRow}>
          <Text style={historyStyles.timelineTitle}>{title}</Text>
          {pill ? <Text style={historyStyles.greenPill}>{pill}</Text> : null}
        </View>
        <Text style={historyStyles.timelineMeta}>○  {meta}</Text>
      </View>
    </View>
  );
}

function HistoryRouteList() {
  const [expandedRoute, setExpandedRoute] = useState<string | null>(null);
  const routes = [
    ['Today', 'Home -> School', '4.2 km - 32 min', 'Completed', '#22C55E'],
    ['Today', 'School -> Home', '4.2 km - 30 min', 'Completed', '#22C55E'],
    ['Yesterday', 'Home -> Tuition', '2.1 km - 18 min', 'Deviation', '#F59E0B'],
    ['Mon', 'School -> Home', '4.2 km - --', 'Incomplete', '#EF4444'],
  ];

  return (
    <View style={historyStyles.listBlock}>
      {routes.map(([day, route, meta, status, color]) => (
        <TouchableOpacity
          key={`${day}${route}`}
          activeOpacity={0.86}
          onPress={() => setExpandedRoute(expandedRoute === route ? null : route)}
          style={[historyStyles.routeCard, expandedRoute === route && historyStyles.routeCardExpanded]}
        >
          <View style={historyStyles.routeMainRow}>
            <View style={historyStyles.routeIconBox}>
              <Ionicons name="git-branch-outline" size={34} color={color} />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={historyStyles.routeDay}>{day}</Text>
              <Text style={historyStyles.routeTitle}>{route}</Text>
              <Text style={historyStyles.routeMeta}>{meta}</Text>
            </View>
            <Text style={[historyStyles.statusPill, { color, backgroundColor: `${color}14` }]}>{status}</Text>
            <Ionicons name={expandedRoute === route ? 'chevron-up' : 'chevron-down'} size={18} color="#94A3B8" />
          </View>
          {expandedRoute === route && status === 'Deviation' ? (
            <View style={historyStyles.routeExpanded}>
              <View style={historyStyles.miniRouteMap}>
                <View style={historyStyles.mapPointA} />
                <View style={historyStyles.mapPointMid} />
                <View style={historyStyles.mapPointB} />
                <View style={historyStyles.routeDashOne} />
                <View style={historyStyles.routeDashTwo} />
                <Text style={historyStyles.mapLabelA}>A</Text>
                <Text style={historyStyles.mapLabelB}>B</Text>
                <Text style={historyStyles.warningMapIcon}>!</Text>
              </View>
              <View style={historyStyles.routeSteps}>
                <HistoryStep number="1" title="Home" subtitle="Start" color="#0B84FF" />
                <HistoryStep number="2" title="Midpoint" subtitle="2.1 km" color="#94A3B8" />
                <HistoryStep number="3" title="Tuition" subtitle="Destination" color="#22C55E" />
              </View>
              <View style={historyStyles.deviationNote}>
                <Text style={historyStyles.deviationTitle}>! Deviation Note</Text>
                <Text style={historyStyles.deviationText}>Deviated near Sector 15 market for 6 min</Text>
              </View>
            </View>
          ) : null}
        </TouchableOpacity>
      ))}
    </View>
  );
}

function HistoryStep({ number, title, subtitle, color }: any) {
  return (
    <View style={historyStyles.stepRow}>
      <View style={[historyStyles.stepBubble, { backgroundColor: color }]}>
        <Text style={historyStyles.stepNumber}>{number}</Text>
      </View>
      <Text style={historyStyles.stepTitle}>{title}</Text>
      <Text style={historyStyles.stepSub}> - {subtitle}</Text>
    </View>
  );
}

function LegacyHistoryRouteList() {
  return (
    <View style={historyStyles.listBlock}>
      {[
        ['Today', 'Home → School', '4.2 km · 32 min', 'Completed', '#22C55E'],
        ['Today', 'School → Home', '4.2 km · 30 min', 'Completed', '#22C55E'],
        ['Yesterday', 'Home → Tuition', '2.1 km · 18 min', 'Deviation', '#F59E0B'],
        ['Mon', 'School → Home', '4.2 km · —', 'Incomplete', '#EF4444'],
      ].map(([day, route, meta, status, color]) => (
        <View key={`${day}${route}`} style={historyStyles.routeCard}>
          <View style={historyStyles.routeIconBox}><Ionicons name="git-branch-outline" size={34} color={color} /></View>
          <View style={{ flex: 1 }}>
            <Text style={historyStyles.routeDay}>{day}</Text>
            <Text style={historyStyles.routeTitle}>{route}</Text>
            <Text style={historyStyles.routeMeta}>{meta}</Text>
          </View>
          <Text style={[historyStyles.statusPill, { color, backgroundColor: `${color}14` }]}>{status}</Text>
          <Ionicons name="chevron-down" size={18} color="#94A3B8" />
        </View>
      ))}
    </View>
  );
}

function HistorySosCard() {
  return (
    <View style={historyStyles.sosCard}>
      <View style={historyStyles.sosHeader}>
        <View>
          <Text style={historyStyles.sosEvent}>SOS EVENT</Text>
          <Text style={historyStyles.sosTitle}>Jun 12 · 10:02 AM</Text>
        </View>
        <View>
          <Text style={historyStyles.resolvedPill}>Resolved</Text>
          <Text style={historyStyles.sosDuration}>Duration: 10 min</Text>
        </View>
      </View>
      <View style={historyStyles.sosBody}>
        <Text style={historyStyles.sectionLabel}>EMERGENCY TIMELINE</Text>
        {[
          ['10:02 AM', 'SOS Triggered by Priya'],
          ['10:03 AM', 'Parent Notified'],
          ['10:03 AM', 'Co-Parent Notified'],
          ['10:04 AM', 'Live Location Shared'],
          ['10:05 AM', 'Parent Acknowledged'],
          ['10:12 AM', 'Resolved by Parent'],
        ].map(([time, text]) => (
          <View key={`${time}${text}`} style={historyStyles.sosLine}>
            <Ionicons name="checkmark-circle-outline" size={24} color="#22C55E" />
            <Text style={historyStyles.sosTime}>{time}</Text>
            <Text style={historyStyles.sosText}>{text} ✓</Text>
          </View>
        ))}
        <View style={historyStyles.sosDetails}>
          <HistoryDetail label="Location" value="MG Road, Sector 18, Noida" />
          <HistoryDetail label="Resolved by" value="Rajesh Sharma (Parent)" />
          <HistoryDetail label="Response time" value="58 seconds" />
        </View>
      </View>
    </View>
  );
}

function HistoryDetail({ label, value }: any) {
  return (
    <View style={historyStyles.detailRow}>
      <Text style={historyStyles.detailLabel}>{label}</Text>
      <Text style={historyStyles.detailValue}>{value}</Text>
    </View>
  );
}

function HistorySafeWalkList() {
  const [expandedWalk, setExpandedWalk] = useState<string | null>(null);
  const walks = [
    ['TODAY - 08:38 AM', 'Home -> School', '24 min - 4.2 km - Rajesh', 'Safe Arrival', '#22C55E'],
    ['YESTERDAY - 03:05 PM', 'School -> Home', '31 min - 4.2 km - Sunita', 'Safe Arrival', '#22C55E'],
    ['MON - 08:40 AM', 'Home -> School', '28 min - 4.2 km - Rajesh', 'Deviation Detected', '#F59E0B'],
  ];

  return (
    <View style={historyStyles.listBlock}>
      {walks.map(([time, title, meta, status, color]) => (
        <TouchableOpacity
          key={time}
          activeOpacity={0.86}
          onPress={() => setExpandedWalk(expandedWalk === time ? null : time)}
          style={[historyStyles.walkCard, expandedWalk === time && historyStyles.walkCardExpanded]}
        >
          <View style={historyStyles.historyTitleRow}>
            <View style={{ flex: 1 }}>
              <Text style={historyStyles.routeDay}>{time}</Text>
              <Text style={historyStyles.routeTitle}>{title}</Text>
              <Text style={historyStyles.routeMeta}>o  {meta}</Text>
              {status === 'Deviation Detected' ? <Text style={historyStyles.alertDuring}>Alert during walk</Text> : null}
            </View>
            <Text style={[historyStyles.statusPill, { color, backgroundColor: `${color}14` }]}>{status}</Text>
          </View>
          {expandedWalk === time ? (
            <View style={historyStyles.walkDetails}>
              <HistoryDetail label="Guardian" value={meta.includes('Sunita') ? 'Sunita Sharma' : 'Rajesh Sharma'} />
              <HistoryDetail label="Route" value={title} />
              <HistoryDetail label="Monitoring" value={status === 'Deviation Detected' ? 'Alert raised during walk' : 'Completed safely'} />
            </View>
          ) : null}
        </TouchableOpacity>
      ))}
    </View>
  );
}

function LegacyHistorySafeWalkList() {
  return (
    <View style={historyStyles.listBlock}>
      {[
        ['TODAY · 08:38 AM', 'Home → School', '24 min · 4.2 km · Rajesh', 'Safe Arrival', '#22C55E'],
        ['YESTERDAY · 03:05 PM', 'School → Home', '31 min · 4.2 km · Sunita', 'Safe Arrival', '#22C55E'],
        ['MON · 08:40 AM', 'Home → School', '28 min · 4.2 km · Rajesh', 'Deviation Detected', '#F59E0B'],
      ].map(([time, title, meta, status, color]) => (
        <View key={time} style={historyStyles.walkCard}>
          <View style={{ flex: 1 }}>
            <Text style={historyStyles.routeDay}>{time}</Text>
            <Text style={historyStyles.routeTitle}>{title}</Text>
            <Text style={historyStyles.routeMeta}>○  {meta}</Text>
            {status === 'Deviation Detected' ? <Text style={historyStyles.alertDuring}>Alert during walk</Text> : null}
          </View>
          <Text style={[historyStyles.statusPill, { color, backgroundColor: `${color}14` }]}>{status}</Text>
        </View>
      ))}
    </View>
  );
}

function HistoryEventList({ type }: { type: string }) {
  const [alertFilter, setAlertFilter] = useState('All');
  const data: Record<string, [string, string, string, string, string][]> = {
    permissions: [
      ['location-outline', '#22C55E', 'Location Enabled', 'Jun 12, 8:00 AM - by Priya', 'Enabled'],
      ['notifications-outline', '#EF4444', 'Microphone Disabled', 'Jun 11, 3:45 PM - by Priya', 'Disabled'],
      ['watch-outline', '#0B84FF', 'Wearable Connected', 'Jun 10, 9:30 AM', 'Connected'],
      ['shield-outline', '#22C55E', 'Background Monitoring Enabled', 'Jun 9', 'Enabled'],
    ],
    devices: [
      ['watch-outline', '#22C55E', 'Apple Watch - Connected', 'Jun 12, 8:05 AM - Battery 72%', ''],
      ['watch-outline', '#EF4444', 'Apple Watch - Disconnected', 'Jun 11, 11:30 PM', ''],
      ['battery-dead-outline', '#F59E0B', 'Apple Watch - Battery Low 15%', 'Jun 11, 6:00 PM', ''],
      ['key-outline', '#0B84FF', 'Keychain - Last Sync', 'Jun 12, Just now', ''],
    ],
    family: [
      ['person-add-outline', '#22C55E', 'Co-Parent Added', 'Jun 5 - Sunita Sharma joined', ''],
      ['shield-outline', '#0B84FF', 'Protected Member Added', 'Jun 5 - Priya (Child) joined', ''],
      ['qr-code-outline', '#8B5CF6', 'QR Code Generated', 'Jun 5 - Used by Priya', ''],
      ['card-outline', '#F59E0B', 'Subscription Purchased', 'Jun 5 - Premium Family Circle Rs299/mo', ''],
      ['notifications-outline', '#EF4444', 'Permission Changed', 'Jun 12 - Microphone disabled by Priya', ''],
    ],
    alerts: [
      ['warning-outline', '#EF4444', 'SOS Triggered', 'Today 10:02 AM - Priya', 'Emergency'],
      ['navigate-outline', '#F59E0B', 'Route Deviation', 'Today 2:15 PM - Priya', 'Warning'],
      ['battery-dead-outline', '#F59E0B', 'Battery 8%', 'Yesterday 3:30 PM - Priya', 'Warning'],
      ['ban-outline', '#0B84FF', 'GPS Disabled', 'Yesterday 9:15 AM - Priya', 'Info'],
    ],
  };
  const rows = type === 'alerts'
    ? data.alerts.filter((item) => alertFilter === 'All' || item[4] === alertFilter)
    : data[type];

  return (
    <View style={historyStyles.eventList}>
      {type === 'alerts' ? (
        <View style={historyStyles.filterRow}>
          {['All', 'Emergency', 'Warning', 'Info'].map((filter) => (
            <TouchableOpacity
              key={filter}
              activeOpacity={0.84}
              onPress={() => setAlertFilter(filter)}
              style={[
                historyStyles.filterPill,
                alertFilter === filter && historyStyles.filterPillActive,
                alertFilter === filter && filter === 'Emergency' && historyStyles.filterEmergency,
                alertFilter === filter && filter === 'Warning' && historyStyles.filterWarning,
              ]}
            >
              <Text style={[historyStyles.filterText, alertFilter === filter && historyStyles.filterTextActive]}>{filter}</Text>
            </TouchableOpacity>
          ))}
        </View>
      ) : null}
      {rows.map(([icon, color, title, meta, status]) => (
        <View key={title} style={historyStyles.eventRow}>
          <View style={[historyStyles.sideDot, { borderColor: color }]} />
          <View style={historyStyles.eventCard}>
            <View style={historyStyles.historyTitleRow}>
              <View style={historyStyles.eventTitleWrap}>
                <Ionicons name={icon as keyof typeof Ionicons.glyphMap} size={18} color={color} />
                <Text style={historyStyles.eventTitle}>{title}</Text>
              </View>
              {status ? <Text style={[historyStyles.statusPill, { color, backgroundColor: `${color}14` }]}>{status === 'Info' ? 'Auto-resolved' : status === 'Emergency' ? 'Resolved' : status === 'Warning' ? (title === 'Route Deviation' ? 'Acknowledged' : 'Resolved') : status}</Text> : null}
            </View>
            <Text style={historyStyles.routeMeta}>{meta}</Text>
            {title === 'SOS Triggered' ? <Text style={historyStyles.responseText}>Response: 4 min</Text> : null}
          </View>
        </View>
      ))}
      {type === 'family' ? (
        <View style={historyStyles.historyNotice}>
          <Ionicons name="diamond-outline" size={22} color="#F59E0B" />
          <View>
            <Text style={historyStyles.historyNoticeTitle}>History available for 90 days</Text>
            <Text style={historyStyles.historyNoticeSub}>Premium Plan - Upgrade for unlimited history</Text>
          </View>
        </View>
      ) : null}
    </View>
  );
}

function LegacyHistoryEventList({ type }: { type: string }) {
  const data: Record<string, [string, string, string, string, string][]> = {
    permissions: [
      ['location-outline', '#22C55E', 'Location Enabled', 'Jun 12, 8:00 AM · by Priya', 'Enabled'],
      ['notifications-outline', '#EF4444', 'Microphone Disabled', 'Jun 11, 3:45 PM · by Priya', 'Disabled'],
      ['watch-outline', '#0B84FF', 'Wearable Connected', 'Jun 10, 9:30 AM', 'Connected'],
      ['shield-outline', '#22C55E', 'Background Monitoring Enabled', 'Jun 9', 'Enabled'],
    ],
    devices: [
      ['watch-outline', '#22C55E', 'Apple Watch — Connected', 'Jun 12, 8:05 AM · Battery 72%', ''],
      ['watch-outline', '#EF4444', 'Apple Watch — Disconnected', 'Jun 11, 11:30 PM', ''],
      ['battery-dead-outline', '#F59E0B', 'Apple Watch — Battery Low 15%', 'Jun 11, 6:00 PM', ''],
      ['key-outline', '#0B84FF', 'Keychain — Last Sync', 'Jun 12, Just now', ''],
    ],
    family: [
      ['person-add-outline', '#22C55E', 'Co-Parent Added', 'Jun 5 · Sunita Sharma joined', ''],
      ['shield-outline', '#0B84FF', 'Protected Member Added', 'Jun 5 · Priya (Child) joined', ''],
      ['qr-code-outline', '#8B5CF6', 'QR Code Generated', 'Jun 5 · Used by Priya', ''],
      ['card-outline', '#F59E0B', 'Subscription Purchased', 'Jun 5 · Premium Family Circle Rs299/mo', ''],
      ['notifications-outline', '#EF4444', 'Permission Changed', 'Jun 12 · Microphone disabled by Priya', ''],
    ],
    alerts: [
      ['warning-outline', '#EF4444', 'SOS Triggered — Aarav', 'Today · 3:42 PM · Sector 12', 'Emergency'],
      ['navigate-outline', '#F59E0B', 'Route Deviation — Aarav', 'Today · 2:15 PM · Sector 18', 'Warning'],
      ['battery-dead-outline', '#F97316', 'Battery Critical 8% — Priya', 'Today · 1:44 PM · MG Road', 'Attention'],
    ],
  };

  return (
    <View style={historyStyles.eventList}>
      {data[type].map(([icon, color, title, meta, status]) => (
        <View key={title} style={historyStyles.eventRow}>
          <View style={[historyStyles.sideDot, { borderColor: color }]} />
          <View style={historyStyles.eventCard}>
            <View style={historyStyles.historyTitleRow}>
              <View style={historyStyles.eventTitleWrap}>
                <Ionicons name={icon as keyof typeof Ionicons.glyphMap} size={18} color={color} />
                <Text style={historyStyles.eventTitle}>{title}</Text>
              </View>
              {status ? <Text style={[historyStyles.statusPill, { color, backgroundColor: `${color}14` }]}>{status}</Text> : null}
            </View>
            <Text style={historyStyles.routeMeta}>{meta}</Text>
          </View>
        </View>
      ))}
      {type === 'family' ? (
        <View style={historyStyles.historyNotice}>
          <Ionicons name="diamond-outline" size={22} color="#F59E0B" />
          <View>
            <Text style={historyStyles.historyNoticeTitle}>History available for 90 days</Text>
            <Text style={historyStyles.historyNoticeSub}>Premium Plan · Upgrade for unlimited history</Text>
          </View>
        </View>
      ) : null}
    </View>
  );
}

function ParentSubscriptionScreen({
  onBack,
  onAddMember,
  onInvoices,
  onCancel,
  onCoParent,
  onTransfer,
}: {
  onBack: () => void;
  onAddMember: () => void;
  onInvoices: () => void;
  onCancel: () => void;
  onCoParent: () => void;
  onTransfer: () => void;
}) {
  return (
    <SafeAreaView style={subStyles.safe} edges={['top']}>
      <View style={subStyles.header}>
        <TouchableOpacity activeOpacity={0.82} onPress={onBack} style={subStyles.backBtn}>
          <Ionicons name="chevron-back" size={25} color="#0F172A" />
        </TouchableOpacity>
        <Text style={subStyles.headerTitle}>Subscription</Text>
      </View>
      <ScrollView style={subStyles.scroll} contentContainerStyle={subStyles.content} showsVerticalScrollIndicator={false}>
        <LinearGradient colors={['#11B6F4', '#26E36E']} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={subStyles.currentPlan}>
          <Text style={subStyles.planLabel}>CURRENT PLAN</Text>
          <Text style={subStyles.planName}>Premium Family Circle</Text>
          <Text style={subStyles.planMeta}>1 Parent - 1 Co-Parent - 1 Protected Member</Text>
          <Text style={subStyles.bigPrice}>₹299<Text style={subStyles.month}>/month</Text></Text>
          <View style={subStyles.planFoot}>
            <Text style={subStyles.planSmall}>Next renewal: 15 Jan 2026</Text>
            <Text style={subStyles.planSmall}>Billing: Rajesh Sharma</Text>
          </View>
        </LinearGradient>

        <Text style={subStyles.sectionLabel}>PLAN MEMBERS</Text>
        <View style={subStyles.card}>
          <PlanMember emoji="👨" name="Rajesh Sharma" role="Parent" badge="You" />
          <PlanMember emoji="👩" name="Sunita Sharma" role="Co-Parent" bordered />
          <PlanMember emoji="👧" name="Priya" role="Child - Protected" badge="Child" bordered purple />
        </View>

        <Text style={subStyles.sectionLabel}>ADD PROTECTED MEMBER</Text>
        <View style={subStyles.addMemberCard}>
          <Text style={subStyles.addMemberTitle}>Current plan: 1 Protected Member included</Text>
          <Text style={subStyles.addMemberSub}>Add more for ₹99/member/month</Text>
          <TouchableOpacity activeOpacity={0.86} onPress={onAddMember} style={subStyles.addProtectedBtn}>
            <Ionicons name="person-add-outline" size={20} color="#FFFFFF" />
            <Text style={subStyles.addProtectedText}>+ Add Protected Member</Text>
          </TouchableOpacity>
        </View>

        <Text style={subStyles.sectionLabel}>BILLING</Text>
        <View style={subStyles.card}>
          <SettingsActionRow icon="card-outline" color="#0EA5E9" title="Manage Payment Method" subtitle="Visa ending 4242" />
          <SettingsActionRow icon="card-outline" color="#22C55E" title="View Invoices" subtitle="3 past invoices" onPress={onInvoices} bordered />
          <SettingsActionRow icon="trash-outline" color="#EF4444" title="Cancel Subscription" subtitle="Effective end of billing cycle" onPress={onCancel} bordered danger />
        </View>

        <Text style={subStyles.sectionLabel}>CO-PARENT</Text>
        <View style={subStyles.card}>
          <SettingsActionRow icon="person-outline" color="#22C55E" title="Sunita Sharma" subtitle="Co-Parent - Monitoring access only" />
          <SettingsActionRow icon="refresh-outline" color="#F59E0B" title="Change Co-Parent" subtitle="Remove current - Generate new invite" onPress={onCoParent} bordered />
        </View>

        <Text style={subStyles.sectionLabel}>OWNERSHIP</Text>
        <View style={subStyles.card}>
          <SettingsActionRow icon="diamond-outline" color="#F59E0B" title="Transfer Primary Ownership" subtitle="Transfer full control to another guardian" onPress={onTransfer} />
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

function PlanMember({ emoji, name, role, badge, bordered, purple }: any) {
  return (
    <View style={[subStyles.memberRow, bordered && subStyles.rowBorder]}>
      <Text style={subStyles.memberEmoji}>{emoji}</Text>
      <View style={{ flex: 1 }}>
        <Text style={subStyles.memberName}>{name}</Text>
        <Text style={subStyles.memberRole}>{role}</Text>
      </View>
      {badge ? <Text style={[subStyles.memberBadge, purple && subStyles.memberBadgePurple]}>{badge}</Text> : null}
    </View>
  );
}

function SettingsActionRow({ icon, color, title, subtitle, onPress, bordered, danger }: any) {
  return (
    <TouchableOpacity activeOpacity={0.78} onPress={onPress} style={[subStyles.actionRow, bordered && subStyles.rowBorder]}>
      <View style={[subStyles.actionIcon, { backgroundColor: `${color}14` }]}>
        <Ionicons name={icon as keyof typeof Ionicons.glyphMap} size={22} color={color} />
      </View>
      <View style={{ flex: 1 }}>
        <Text style={[subStyles.actionTitle, danger && subStyles.dangerTitle]}>{title}</Text>
        <Text style={subStyles.actionSub}>{subtitle}</Text>
      </View>
      <Ionicons name="chevron-forward" size={18} color="#CBD5E1" />
    </TouchableOpacity>
  );
}

function ParentSettingsSheet({
  type,
  onClose,
  onAddEmergencyContact,
}: {
  type: null | 'member' | 'invoices' | 'cancel' | 'coparent' | 'transfer' | 'emergencyContact';
  onClose: () => void;
  onAddEmergencyContact?: (contactType: string) => void;
}) {
  const [selectedMember, setSelectedMember] = useState<string | null>(null);
  const [memberStep, setMemberStep] = useState<'select' | 'invite' | 'payment' | 'qr' | 'code'>('select');
  const [memberDelivery, setMemberDelivery] = useState<'qr' | 'code' | null>(null);
  const [memberInviteSeconds, setMemberInviteSeconds] = useState(15 * 60);
  const [selectedContact, setSelectedContact] = useState<string | null>(null);
  const [confirmName, setConfirmName] = useState('');
  useEffect(() => {
    if (type !== 'member') {
      setSelectedMember(null);
      setMemberStep('select');
      setMemberDelivery(null);
      return;
    }
    if (memberStep !== 'qr' && memberStep !== 'code') return;
    setMemberInviteSeconds(15 * 60);
    const timer = setInterval(() => {
      setMemberInviteSeconds((seconds) => Math.max(0, seconds - 1));
    }, 1000);
    return () => clearInterval(timer);
  }, [type, memberStep]);
  if (!type) return null;

  const isTransferValid = confirmName.trim() === 'Rajesh Sharma';
  const memberTypes = [
    ['👧', 'Child', 'Age-appropriate safety features'],
    ['👩', 'Woman', 'Personal safety & SOS'],
    ['👴', 'Senior', 'Medical alerts & check-ins'],
    ['👨‍👩‍👧', 'Family Member', 'General family safety'],
  ];
  const selectedMemberData = memberTypes.find(([, title]) => title === selectedMember) ?? memberTypes[0];
  const inviteMinutes = Math.floor(memberInviteSeconds / 60).toString().padStart(2, '0');
  const inviteSeconds = (memberInviteSeconds % 60).toString().padStart(2, '0');
  const contactTypes = ['Doctor', 'Relative', 'Neighbor', 'Teacher', 'Building Security', 'Family Friend'];

  return (
    <View style={sheetStyles.layer}>
      <TouchableOpacity activeOpacity={1} style={sheetStyles.backdrop} onPress={onClose} />
      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : 'height'} style={sheetStyles.avoider}>
        <View style={[sheetStyles.sheet, type === 'transfer' && sheetStyles.transferSheet, type === 'emergencyContact' && sheetStyles.contactSheet]}>
          <View style={sheetStyles.handle} />

          {type === 'member' && memberStep === 'select' ? (
            <>
              <Text style={sheetStyles.centerTitle}>Choose Member Type</Text>
              <Text style={sheetStyles.centerSub}>₹99/month per additional member</Text>
              <View style={sheetStyles.memberGrid}>
                {memberTypes.map(([emoji, title, sub]) => (
                  <TouchableOpacity key={title} activeOpacity={0.82} onPress={() => setSelectedMember(title)} style={[sheetStyles.memberTypeCard, selectedMember === title && sheetStyles.memberTypeSelected]}>
                    <Text style={sheetStyles.memberTypeEmoji}>{emoji}</Text>
                    <Text style={sheetStyles.memberTypeTitle}>{title}</Text>
                    <Text style={sheetStyles.memberTypeSub}>{sub}</Text>
                  </TouchableOpacity>
                ))}
              </View>
              <TouchableOpacity activeOpacity={0.86} disabled={!selectedMember} onPress={() => selectedMember && setMemberStep('invite')} style={[sheetStyles.primaryBtn, !selectedMember && sheetStyles.disabledBtn]}>
                <Text style={sheetStyles.primaryText}>Continue</Text>
              </TouchableOpacity>
              <TouchableOpacity activeOpacity={0.82} onPress={onClose} style={sheetStyles.plainBtn}>
                <Text style={sheetStyles.plainText}>Cancel</Text>
              </TouchableOpacity>
            </>
          ) : null}

          {type === 'member' && memberStep === 'invite' ? (
            <>
              <Text style={sheetStyles.centerTitle}>Invite New Member</Text>
              <Text style={sheetStyles.centerSub}>{selectedMemberData[0]} {selectedMemberData[1]}</Text>
              <View style={sheetStyles.pricePanel}>
                <Text style={sheetStyles.priceLabel}>Add-on price</Text>
                <Text style={sheetStyles.priceBig}>₹99<Text style={sheetStyles.priceSmall}>/member/mo</Text></Text>
              </View>
              <View style={sheetStyles.inviteActions}>
                <TouchableOpacity
                  activeOpacity={0.86}
                  onPress={() => {
                    setMemberDelivery('qr');
                    setMemberStep('payment');
                  }}
                  style={sheetStyles.outlineBlueBtn}
                >
                  <Ionicons name="qr-code-outline" size={20} color="#0B84FF" />
                  <Text style={sheetStyles.outlineBlueText}>Generate QR</Text>
                </TouchableOpacity>
                <TouchableOpacity
                  activeOpacity={0.86}
                  onPress={() => {
                    setMemberDelivery('code');
                    setMemberStep('payment');
                  }}
                  style={sheetStyles.compactPrimaryBtn}
                >
                  <Ionicons name="paper-plane-outline" size={20} color="#FFFFFF" />
                  <Text style={sheetStyles.primaryText}>Send Invite</Text>
                </TouchableOpacity>
              </View>
              <TouchableOpacity activeOpacity={0.82} onPress={() => setMemberStep('select')} style={sheetStyles.plainBtn}>
                <Text style={sheetStyles.plainText}>← Back</Text>
              </TouchableOpacity>
            </>
          ) : null}

          {type === 'member' && memberStep === 'payment' ? (
            <>
              <Text style={sheetStyles.centerTitle}>Confirm Payment</Text>
              <Text style={sheetStyles.centerSub}>Adding 1 protected member to your plan</Text>
              <View style={sheetStyles.paymentPanel}>
                <View style={sheetStyles.paymentRow}><Text style={sheetStyles.paymentLabel}>Current plan</Text><Text style={sheetStyles.paymentAmount}>₹299/mo</Text></View>
                <View style={sheetStyles.paymentRow}><Text style={sheetStyles.paymentLabel}>Add-on member</Text><Text style={sheetStyles.paymentAmount}>+₹99/mo</Text></View>
                <View style={sheetStyles.paymentRow}><Text style={sheetStyles.paymentLabel}>New total</Text><Text style={sheetStyles.paymentAmount}>₹398/mo</Text></View>
              </View>
              <View style={sheetStyles.paymentNotice}>
                <Ionicons name="warning-outline" size={18} color="#F59E0B" />
                <Text style={sheetStyles.paymentNoticeText}>Charged via Visa ending 4242 · Recurring monthly</Text>
              </View>
              <TouchableOpacity activeOpacity={0.86} onPress={() => setMemberStep(memberDelivery === 'qr' ? 'qr' : 'code')} style={sheetStyles.payBtn}>
                <Text style={sheetStyles.primaryText}>✓  Confirm & Pay ₹99/mo</Text>
              </TouchableOpacity>
              <TouchableOpacity activeOpacity={0.82} onPress={() => setMemberStep('invite')} style={sheetStyles.plainBtn}>
                <Text style={sheetStyles.plainText}>← Back</Text>
              </TouchableOpacity>
            </>
          ) : null}

          {type === 'member' && (memberStep === 'qr' || memberStep === 'code') ? (
            <>
              <Text style={sheetStyles.centerTitle}>{memberStep === 'qr' ? 'QR Invite Ready' : 'Invite Code Ready'}</Text>
              <Text style={sheetStyles.centerSub}>{selectedMemberData[0]} {selectedMemberData[1]} invite active for {inviteMinutes}:{inviteSeconds}</Text>
              {memberStep === 'qr' ? (
                <View style={sheetStyles.memberQrBox}>
                  <FakeQrCode />
                </View>
              ) : (
                <View style={sheetStyles.memberCodeRow}>
                  {'N4H7K2'.split('').map((char) => (
                    <View key={char} style={sheetStyles.memberCodeBox}><Text style={sheetStyles.memberCodeText}>{char}</Text></View>
                  ))}
                </View>
              )}
              <Text style={sheetStyles.inviteCopy}>{memberStep === 'qr' ? 'Ask the new member to scan this QR from their NISCHINT app.' : 'Share this 6-character invite code with the new member.'}</Text>
              <TouchableOpacity activeOpacity={0.86} style={sheetStyles.primaryBtn}>
                <Text style={sheetStyles.primaryText}>{memberStep === 'qr' ? 'Share QR Invite' : 'Share Invite Code'}</Text>
              </TouchableOpacity>
              <TouchableOpacity activeOpacity={0.82} onPress={() => setMemberStep('invite')} style={sheetStyles.plainBtn}>
                <Text style={sheetStyles.plainText}>← Back</Text>
              </TouchableOpacity>
            </>
          ) : null}

          {type === 'emergencyContact' ? (
            <>
              <Text style={sheetStyles.sheetTitle}>Add Emergency Contact</Text>
              <Text style={sheetStyles.leftSub}>Select the contact type</Text>
              <View style={sheetStyles.contactGrid}>
                {contactTypes.map((contactType) => (
                  <TouchableOpacity
                    key={contactType}
                    activeOpacity={0.82}
                    onPress={() => setSelectedContact(contactType)}
                    style={[sheetStyles.contactTypeCard, selectedContact === contactType && sheetStyles.contactTypeSelected]}
                  >
                    <Text style={sheetStyles.contactTypeText}>{contactType}</Text>
                  </TouchableOpacity>
                ))}
              </View>
              <TouchableOpacity
                activeOpacity={0.86}
                disabled={!selectedContact}
                onPress={() => selectedContact && onAddEmergencyContact?.(selectedContact)}
                style={[sheetStyles.primaryBtn, !selectedContact && sheetStyles.disabledBtn]}
              >
                <Text style={sheetStyles.primaryText}>{selectedContact ? `Add ${selectedContact}` : 'Add Contact'}</Text>
              </TouchableOpacity>
            </>
          ) : null}

          {type === 'invoices' ? (
            <>
              <View style={sheetStyles.sheetTitleRow}>
                <Text style={sheetStyles.sheetTitle}>Past Invoices</Text>
                <TouchableOpacity onPress={onClose}><Ionicons name="close" size={25} color="#64748B" /></TouchableOpacity>
              </View>
              {[
                ['INV-2025-012', '15 Dec 2025'],
                ['INV-2025-011', '15 Nov 2025'],
                ['INV-2025-010', '15 Oct 2025'],
              ].map(([id, date], index) => (
                <View key={id} style={[sheetStyles.invoiceRow, index > 0 && sheetStyles.invoiceBorder]}>
                  <View style={{ flex: 1 }}>
                    <Text style={sheetStyles.invoiceId}>{id}</Text>
                    <Text style={sheetStyles.invoiceDate}>{date}</Text>
                  </View>
                  <Text style={sheetStyles.invoiceAmount}>₹299</Text>
                  <Text style={sheetStyles.paidPill}>Paid</Text>
                </View>
              ))}
            </>
          ) : null}

          {type === 'cancel' ? (
            <>
              <View style={sheetStyles.warningIcon}><Ionicons name="warning-outline" size={42} color="#EF4444" /></View>
              <Text style={sheetStyles.centerTitle}>Cancel Subscription?</Text>
              <Text style={sheetStyles.cancelCopy}>All family members will lose safety monitoring access at the end of the current billing cycle. Your data will be retained for 30 days.</Text>
              <View style={sheetStyles.cancelList}>
                <Text style={sheetStyles.cancelItem}>×  Priya loses location & SOS protection</Text>
                <Text style={sheetStyles.cancelItem}>×  Sunita loses Co-Parent access</Text>
                <Text style={sheetStyles.cancelItem}>×  All AI safety alerts will stop</Text>
              </View>
              <TouchableOpacity activeOpacity={0.86} style={sheetStyles.dangerBtn}>
                <Text style={sheetStyles.primaryText}>Continue to Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity activeOpacity={0.82} onPress={onClose} style={sheetStyles.plainBtn}>
                <Text style={sheetStyles.bluePlainText}>Keep my subscription</Text>
              </TouchableOpacity>
            </>
          ) : null}

          {type === 'coparent' ? (
            <>
              <Text style={sheetStyles.sheetTitle}>Change Co-Parent</Text>
              <View style={sheetStyles.coParentCard}>
                <Text style={sheetStyles.coParentEmoji}>👩</Text>
                <View>
                  <Text style={sheetStyles.coParentName}>Sunita Sharma</Text>
                  <Text style={sheetStyles.coParentSub}>Current Co-Parent - Active</Text>
                </View>
              </View>
              <View style={sheetStyles.orangeNotice}>
                <Ionicons name="warning-outline" size={18} color="#F59E0B" />
                <Text style={sheetStyles.orangeNoticeText}>Removing Sunita will revoke her family access immediately.</Text>
              </View>
              <TouchableOpacity activeOpacity={0.84} style={sheetStyles.outlineDangerBtn}>
                <Text style={sheetStyles.outlineDangerText}>Remove Sunita Sharma</Text>
              </TouchableOpacity>
              <TouchableOpacity activeOpacity={0.86} style={sheetStyles.primaryBtn}>
                <Text style={sheetStyles.primaryText}>⌗  Generate New Invite</Text>
              </TouchableOpacity>
              <TouchableOpacity activeOpacity={0.82} onPress={onClose} style={sheetStyles.plainBtn}>
                <Text style={sheetStyles.plainText}>Cancel</Text>
              </TouchableOpacity>
            </>
          ) : null}

          {type === 'transfer' ? (
            <>
              <View style={sheetStyles.crownIcon}><Ionicons name="diamond-outline" size={34} color="#F59E0B" /></View>
              <Text style={sheetStyles.centerTitle}>Transfer Primary Ownership</Text>
              <Text style={sheetStyles.transferCopy}>This transfers full control of subscription, billing, and family management to another guardian. <Text style={sheetStyles.redStrong}>This action cannot be undone.</Text></Text>
              <View style={sheetStyles.cancelList}>
                <Text style={sheetStyles.cancelItem}>⚠  You will lose billing & payment access</Text>
                <Text style={sheetStyles.cancelItem}>⚠  New owner controls family member management</Text>
                <Text style={sheetStyles.cancelItem}>⚠  Co-Parent permissions may be altered</Text>
              </View>
              <Text style={sheetStyles.confirmLabel}>Type <Text style={sheetStyles.confirmStrong}>Rajesh Sharma</Text> to confirm</Text>
              <TextInput
                value={confirmName}
                onChangeText={setConfirmName}
                style={sheetStyles.confirmInput}
                placeholder="Type your full name..."
                placeholderTextColor="#94A3B8"
              />
              <TouchableOpacity activeOpacity={0.86} style={[sheetStyles.primaryBtn, !isTransferValid && sheetStyles.disabledBtn]}>
                <Text style={sheetStyles.primaryText}>Transfer Ownership</Text>
              </TouchableOpacity>
              <TouchableOpacity activeOpacity={0.82} onPress={onClose} style={sheetStyles.plainBtn}>
                <Text style={sheetStyles.plainText}>Cancel</Text>
              </TouchableOpacity>
            </>
          ) : null}
        </View>
      </KeyboardAvoidingView>
    </View>
  );
}

function WomanSettingsScreen() {
  const router = useRouter();
  const { logout, profileMode } = useAuthStore();
  const isSeniorMode = profileMode === 'senior';
  const [page, setPage] = useState<null | 'profile' | 'family' | 'monitoring' | 'privacy' | 'permissions' | 'notifications' | 'help'>(null);
  const displayName = isSeniorMode ? 'swarangi' : 'swaesrgh';
  const myAccount = [
    ['person-outline', '#0EA5E9', 'Profile', 'Name, phone', []],
    ['people-outline', '#22C55E', 'Family Circle', 'Your guardians', []],
  ] as const;
  const simpleSections = [
    { title: 'PRIVACY & CONSENT', rows: [['document-text-outline', '#8B5CF6', 'Privacy & Consent', 'Policy, consent, data rights', []]] },
    { title: 'PERMISSIONS', rows: [['lock-closed-outline', '#F59E0B', 'Permissions', '', ['Location', 'Notifications', 'Mic', 'Bluetooth']]] },
    { title: 'NOTIFICATIONS', rows: [['notifications-outline', '#F59E0B', 'Notifications', 'SOS, check-ins, routes, guardian', []]] },
    { title: 'HELP', rows: [['help-circle-outline', '#0EA5E9', 'Help', 'Guides, support, report issues', []]] },
  ] as const;

  const handleLogout = async () => {
    await logout();
    router.replace('/intro');
  };

  if (page) {
    return <WomanSettingsDetailScreen page={page} isSeniorMode={isSeniorMode} onBack={() => setPage(null)} />;
  }

  return (
    <SafeAreaView style={womanSettings.safe} edges={['top']}>
      <View style={womanSettings.header}>
        <TouchableOpacity activeOpacity={0.82} style={womanSettings.backBtn}>
          <Ionicons name="chevron-back" size={24} color="#0F172A" />
        </TouchableOpacity>
        <View style={womanSettings.headerCenter}>
          <Text style={womanSettings.userName}>{displayName}</Text>
          <View style={womanSettings.roleRow}>
            <View style={womanSettings.onlineDot} />
            <Text style={[womanSettings.roleText, isSeniorMode && womanSettings.seniorRoleText]}>{isSeniorMode ? 'Senior Citizen - Protected' : 'Woman - Protected'}</Text>
          </View>
        </View>
        <View style={[womanSettings.rolePill, isSeniorMode && womanSettings.seniorRolePill]}>
          <Text style={[womanSettings.rolePillText, isSeniorMode && womanSettings.seniorRolePillText]}>{isSeniorMode ? 'Senior' : 'Woman'}</Text>
        </View>
      </View>

      <ScrollView style={womanSettings.scroll} contentContainerStyle={womanSettings.content} showsVerticalScrollIndicator={false}>
        <View style={womanSettings.brandRow}>
          <View style={womanSettings.brandLeft}>
            <View style={womanSettings.brandIcon}>
              <Ionicons name="shield-checkmark" size={18} color="#FFFFFF" />
            </View>
            <Text style={womanSettings.brandText}>NISCHINT</Text>
          </View>
          <Text style={womanSettings.version}>v1.0.0</Text>
        </View>

        <TouchableOpacity activeOpacity={0.82} onPress={() => setPage('profile')} style={womanSettings.profileCard}>
          <LinearGradient colors={['#0EA5E9', '#22C55E']} style={womanSettings.avatarBox}>
            <Text style={womanSettings.avatarText}>A</Text>
          </LinearGradient>
          <View style={womanSettings.profileCopy}>
            <Text style={womanSettings.profileName}>Aarav</Text>
            <Text style={womanSettings.profileMeta}>Child - Protected Member</Text>
            <Text style={womanSettings.protectedText}>Shield Protected by Rajesh Sharma</Text>
          </View>
          <Ionicons name="chevron-forward" size={18} color="#CBD5E1" />
        </TouchableOpacity>

        <Text style={womanSettings.sectionLabel}>MY ACCOUNT</Text>
        <View style={womanSettings.card}>
          {myAccount.map(([icon, color, title, subtitle], index) => (
            <WomanSettingsRow key={title} icon={icon} color={color} title={title} subtitle={subtitle} bordered={index > 0} onPress={() => setPage(title === 'Profile' ? 'profile' : 'family')} />
          ))}
        </View>

        <Text style={womanSettings.sectionLabel}>MONITORING & DEVICES</Text>
        <TouchableOpacity activeOpacity={0.85} onPress={() => setPage('monitoring')} style={womanSettings.monitoringCard}>
          <View style={womanSettings.monitoringIcon}>
            <Ionicons name="hardware-chip-outline" size={25} color="#FFFFFF" />
          </View>
          <View style={womanSettings.monitoringCopy}>
            <Text style={womanSettings.monitoringTitle}>Monitoring & Devices</Text>
            <Text style={womanSettings.monitoringSub}>AI, location, devices, permissions</Text>
            <View style={womanSettings.chipRow}>
              {['AI', 'Location', 'Mic', 'Watch'].map((chip) => (
                <Text key={chip} style={womanSettings.blueChip}>{chip}</Text>
              ))}
            </View>
          </View>
          <Ionicons name="chevron-forward" size={20} color="#FFFFFF" />
        </TouchableOpacity>

        {simpleSections.map((section) => (
          <View key={section.title}>
            <Text style={womanSettings.sectionLabel}>{section.title}</Text>
            <View style={womanSettings.card}>
              {section.rows.map(([icon, color, title, subtitle, chips]) => (
                <WomanSettingsRow
                  key={title}
                  icon={icon}
                  color={color}
                  title={title}
                  subtitle={subtitle}
                  chips={chips}
                  onPress={() => setPage(title === 'Privacy & Consent' ? 'privacy' : title === 'Permissions' ? 'permissions' : title === 'Notifications' ? 'notifications' : title === 'Help' ? 'help' : null)}
                />
              ))}
            </View>
          </View>
        ))}

        <Text style={womanSettings.sectionLabel}>ACCOUNT SECURITY</Text>
        <TouchableOpacity activeOpacity={0.82} style={womanSettings.logoutCard} onPress={handleLogout}>
          <View style={[womanSettings.rowIcon, { backgroundColor: '#FEF2F2' }]}>
            <Ionicons name="log-out-outline" size={21} color="#EF4444" />
          </View>
          <View style={womanSettings.rowCopy}>
            <Text style={womanSettings.logoutTitle}>Logout</Text>
            <Text style={womanSettings.rowSub}>Requires guardian approval</Text>
          </View>
          <Ionicons name="chevron-forward" size={18} color="#CBD5E1" />
        </TouchableOpacity>
        <Text style={womanSettings.footer}>NISCHINT - Protection Always On</Text>
      </ScrollView>
    </SafeAreaView>
  );
}

function WomanSettingsDetailScreen({ page, isSeniorMode, onBack }: { page: 'profile' | 'family' | 'monitoring' | 'privacy' | 'permissions' | 'notifications' | 'help'; isSeniorMode: boolean; onBack: () => void }) {
  const [monitorTab, setMonitorTab] = useState<'Monitoring' | 'Devices' | 'Permissions'>(
    page === 'permissions' ? 'Permissions' : 'Monitoring'
  );
  const name = isSeniorMode ? 'swarangi' : 'fcwhgcj';
  const role = isSeniorMode ? 'Senior Citizen - Protected' : 'Woman - Protected';
  const title = page === 'profile' ? 'Profile'
    : page === 'family' ? 'Family Circle'
    : page === 'monitoring' ? 'Monitoring & Devices'
    : page === 'privacy' ? 'Privacy & Consent'
    : page === 'permissions' ? 'Permissions'
    : page === 'notifications' ? 'Notifications'
    : 'Help';

  const monitoringRows = [
    ['AI Monitoring', 'Smart threat detection & analysis', 'ON'],
    ['Location Monitoring', 'Real-time GPS tracking', 'ON'],
    ['Microphone Detection', 'Enable in Privacy settings', 'OFF'],
    ['Route Monitoring', 'Safe route deviation alerts', 'ON'],
    ['Background Protection', 'Active even when app is closed', 'ON'],
    ['Safety Check', 'Periodic check-in reminders', 'ON'],
  ];
  const deviceRows = [
    ['watch-outline', 'Smart Watch', 'Connected - Last sync: 2m ago', '72%', ['SOS: ON', 'Location: ON']],
    ['key-outline', 'Safety Keychain', 'Connected - Last sync: 5m ago', '88%', ['Emergency Alert', 'Guardian Alerts']],
    ['ellipse-outline', 'Smart Band', 'Not Connected', '', ['+ Pair Device']],
  ] as const;
  const permissionRows = [
    ['location-outline', '#22C55E', 'Location', 'Enabled', ['Real-time GPS tracking', 'Route monitoring & deviation alerts', 'Emergency location sharing']],
    ['notifications-outline', '#22C55E', 'Notifications', 'Enabled', ['SOS & safety alerts', 'Guardian messages', 'Battery & route reminders']],
    ['mic-outline', '#EF4444', 'Microphone', 'Not Granted', ['Voice distress detection', 'AI audio threat analysis', 'Hands-free SOS trigger']],
    ['bluetooth-outline', '#22C55E', 'Bluetooth', 'Enabled', ['Connected device syncing', 'Smart Watch & Keychain pairing', 'Proximity-based alerts']],
    ['radio-outline', '#22C55E', 'Background Activity', 'Enabled', ['Always-on protection', 'Silent SOS trigger', 'Passive monitoring when screen off']],
    ['camera-outline', '#F59E0B', 'Camera', 'Optional', ['Profile photo capture', 'QR code scanning', 'Evidence photo logging']],
  ] as const;

  return (
    <SafeAreaView style={womanSettings.safe} edges={['top']}>
      <View style={womanSettings.header}>
        <TouchableOpacity activeOpacity={0.82} style={womanSettings.backBtn} onPress={onBack}>
          <Ionicons name="chevron-back" size={24} color="#0F172A" />
        </TouchableOpacity>
        <View style={womanSettings.headerCenter}>
          <Text style={womanSettings.userName}>{name}</Text>
          <View style={womanSettings.roleRow}>
            <View style={womanSettings.onlineDot} />
            <Text style={[womanSettings.roleText, isSeniorMode && womanSettings.seniorRoleText]}>{role}</Text>
          </View>
        </View>
        <View style={[womanSettings.rolePill, isSeniorMode && womanSettings.seniorRolePill]}>
          <Text style={[womanSettings.rolePillText, isSeniorMode && womanSettings.seniorRolePillText]}>{isSeniorMode ? 'Senior' : 'Woman'}</Text>
        </View>
      </View>
      <View style={womanSettings.detailTitleBar}>
        <TouchableOpacity activeOpacity={0.82} style={womanSettings.backBtn} onPress={onBack}>
          <Ionicons name="arrow-back" size={22} color="#0F172A" />
        </TouchableOpacity>
        <Text style={womanSettings.detailTitle}>{title}</Text>
      </View>

      <ScrollView style={womanSettings.scroll} contentContainerStyle={womanSettings.detailContent} showsVerticalScrollIndicator={false}>
        {page === 'profile' ? (
          <>
            <View style={womanSettings.profileHero}>
              <LinearGradient colors={['#0EA5E9', '#22C55E']} style={womanSettings.profileAvatarLarge}>
                <Text style={womanSettings.profileAvatarText}>A</Text>
              </LinearGradient>
              <Text style={womanSettings.profileHeroName}>Aarav Sharma</Text>
              <Text style={womanSettings.profileHeroMeta}>Child - Protected Member</Text>
            </View>
            <View style={womanSettings.detailCard}>
              {[
                ['FULL NAME', 'Aarav Sharma'],
                ['PHONE', '+91 98765 43210'],
                ['DATE OF BIRTH', 'March 12, 2010'],
                ['MEMBER SINCE', 'January 2024'],
              ].map(([label, value], index) => (
                <View key={label} style={[womanSettings.profileInfoRow, index > 0 && womanSettings.profileInfoBorder]}>
                  <Text style={womanSettings.infoLabel}>{label}</Text>
                  <Text style={womanSettings.infoValue}>{value}</Text>
                </View>
              ))}
            </View>
            <View style={womanSettings.managedNotice}>
              <Ionicons name="lock-closed-outline" size={20} color="#B45309" />
              <Text style={womanSettings.managedNoticeText}>Profile details are managed by your guardian. Contact them to make changes.</Text>
            </View>
          </>
        ) : null}

        {page === 'family' ? (
          <>
            <Text style={womanSettings.familyNote}>Your guardians can view your location and protection status.</Text>
            {[
              ['R', 'Rajesh Sharma', 'Primary Guardian - Father', '#0B8FF0'],
              ['P', 'Priya Sharma', 'Co-Guardian - Mother', '#22C55E'],
            ].map(([initial, guardianName, sub, color]) => (
              <View key={guardianName} style={womanSettings.guardianPersonCard}>
                <View style={[womanSettings.guardianInitial, { backgroundColor: color }]}><Text style={womanSettings.guardianInitialText}>{initial}</Text></View>
                <View style={{ flex: 1 }}>
                  <Text style={womanSettings.guardianName}>{guardianName}</Text>
                  <Text style={womanSettings.guardianSub}>{sub}</Text>
                </View>
                <Ionicons name="shield-checkmark-outline" size={22} color="#22C55E" />
              </View>
            ))}
            <View style={womanSettings.protectedNotice}>
              <Ionicons name="checkmark" size={20} color="#16A34A" />
              <Text style={womanSettings.protectedNoticeText}>You are protected by 2 guardians. Your safety circle is active.</Text>
            </View>
          </>
        ) : null}

        {page === 'monitoring' ? (
          <>
            <View style={womanSettings.detailTabs}>
              {(['Monitoring', 'Devices', 'Permissions'] as const).map((tab) => (
                <TouchableOpacity key={tab} activeOpacity={0.82} onPress={() => setMonitorTab(tab)} style={[womanSettings.detailTab, monitorTab === tab && womanSettings.detailTabActive]}>
                  <Text style={[womanSettings.detailTabText, monitorTab === tab && womanSettings.detailTabTextActive]}>{tab}</Text>
                </TouchableOpacity>
              ))}
            </View>
            {monitorTab === 'Monitoring' ? (
              <View style={womanSettings.detailCard}>
                {monitoringRows.map(([rowTitle, sub, state], index) => (
                  <View key={rowTitle} style={[womanSettings.monitorDetailRow, index > 0 && womanSettings.profileInfoBorder]}>
                    <View style={{ flex: 1 }}>
                      <Text style={womanSettings.monitorDetailTitle}>{rowTitle}</Text>
                      <Text style={womanSettings.monitorDetailSub}>{sub}</Text>
                    </View>
                    <Text style={[womanSettings.stateBadge, state === 'OFF' && womanSettings.stateOff]}>{state}</Text>
                  </View>
                ))}
              </View>
            ) : null}
            {monitorTab === 'Devices' ? (
              <>
                {deviceRows.map(([icon, device, sub, battery, actions]) => (
                  <View key={device} style={womanSettings.deviceDetailCard}>
                    <View style={womanSettings.deviceTitleRow}>
                      <Ionicons name={icon as keyof typeof Ionicons.glyphMap} size={30} color="#6366F1" />
                      <View style={{ flex: 1 }}>
                        <Text style={womanSettings.deviceTitle}>{device}</Text>
                        <Text style={[womanSettings.deviceSub, sub.includes('Not') && womanSettings.deviceOff]}>{sub}</Text>
                      </View>
                    </View>
                    {battery ? <View style={womanSettings.batteryLine}><View style={[womanSettings.batteryFill, { width: battery }]} /></View> : null}
                    {battery ? <Text style={womanSettings.batteryText}>{battery}</Text> : null}
                    {actions.map((action) => (
                      <View key={action} style={womanSettings.deviceActionRow}>
                        <Text style={womanSettings.deviceActionText}>{action}</Text>
                        {action.startsWith('+') ? <Text style={womanSettings.pairButton}>{action}</Text> : <Switch value disabled trackColor={{ false: '#CBD5E1', true: '#0B8FF0' }} thumbColor="#FFFFFF" />}
                      </View>
                    ))}
                  </View>
                ))}
                <View style={womanSettings.addDeviceDashed}><Text style={womanSettings.addDeviceText}>+  Add New Device</Text></View>
              </>
            ) : null}
            {monitorTab === 'Permissions' ? <PermissionDetailList rows={permissionRows} /> : null}
          </>
        ) : null}

        {page === 'privacy' ? (
          <View style={womanSettings.privacyList}>
            {[
              ['document-text-outline', '#8B5CF6', 'Privacy Policy', 'View NISCHINT privacy policy'],
              ['document-text-outline', '#8B5CF6', 'Terms & Conditions', 'View terms of use'],
              ['checkmark-outline', '#22C55E', 'Consent Status', 'Location - Monitoring - Notifications active'],
              ['download-outline', '#0EA5E9', 'Download My Data', 'Export your data as PDF/JSON'],
              ['warning-outline', '#F59E0B', 'Withdraw Consent', 'Requires 72-hour cooling period'],
              ['trash-outline', '#EF4444', 'Delete Account', 'Requires guardian OTP approval'],
            ].map(([icon, color, rowTitle, sub]) => (
              <WomanSettingsRow key={rowTitle} icon={icon} color={color} title={rowTitle} subtitle={sub} />
            ))}
          </View>
        ) : null}

        {page === 'permissions' ? <PermissionDetailList rows={permissionRows} /> : null}

        {page === 'notifications' ? (
          <View style={womanSettings.detailCard}>
            {[
              ['SOS Alerts', 'Emergency alert notifications', 'Always ON'],
              ['Safety Check Reminders', 'Periodic check-in prompts', ''],
              ['Route Alerts', 'Deviation & arrival updates', ''],
              ['Guardian Messages', 'Messages from your guardians', ''],
              ['Battery Alerts', 'Low battery warnings', ''],
            ].map(([rowTitle, sub, fixed], index) => (
              <View key={rowTitle} style={[womanSettings.notificationRow, index > 0 && womanSettings.profileInfoBorder]}>
                <View style={{ flex: 1 }}>
                  <Text style={womanSettings.monitorDetailTitle}>{rowTitle}</Text>
                  <Text style={womanSettings.monitorDetailSub}>{sub}</Text>
                </View>
                {fixed ? <Text style={womanSettings.alwaysOn}>{fixed}</Text> : <Switch value trackColor={{ false: '#CBD5E1', true: '#0B8FF0' }} thumbColor="#FFFFFF" />}
              </View>
            ))}
          </View>
        ) : null}

        {page === 'help' ? (
          <View style={womanSettings.privacyList}>
            {[
              ['help-circle-outline', '#0EA5E9', 'How to use NISCHINT', 'Guides & tutorials'],
              ['chatbubble-outline', '#22C55E', 'Contact Support', 'Chat or email our team'],
              ['warning-outline', '#F59E0B', 'Report an Issue', 'Submit a bug or concern'],
            ].map(([icon, color, rowTitle, sub]) => (
              <WomanSettingsRow key={rowTitle} icon={icon} color={color} title={rowTitle} subtitle={sub} />
            ))}
          </View>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

function PermissionDetailList({ rows }: any) {
  return (
    <>
      {rows.map(([icon, color, title, status, bullets]: any) => (
        <View key={title} style={womanSettings.permissionDetailCard}>
          <View style={womanSettings.permissionHead}>
            <View style={[womanSettings.rowIcon, { backgroundColor: `${color}18` }]}>
              <Ionicons name={icon as keyof typeof Ionicons.glyphMap} size={23} color={color} />
            </View>
            <Text style={womanSettings.permissionTitle}>{title}</Text>
            <Text style={[womanSettings.permissionStatePill, status === 'Not Granted' && womanSettings.permissionDenied, status === 'Optional' && womanSettings.permissionOptional]}>{status}</Text>
          </View>
          {bullets.map((bullet: string) => <Text key={bullet} style={womanSettings.permissionBullet}>⊙  {bullet}</Text>)}
          {title === 'Microphone' ? <Text style={womanSettings.systemSettingsBtn}>⚙  Open System Settings</Text> : null}
        </View>
      ))}
    </>
  );
}

function WomanSettingsRow({ icon, color, title, subtitle, bordered, chips, onPress }: any) {
  return (
    <TouchableOpacity activeOpacity={0.78} onPress={onPress} style={[womanSettings.row, bordered && womanSettings.rowBorder]}>
      <View style={[womanSettings.rowIcon, { backgroundColor: `${color}14` }]}>
        <Ionicons name={icon as keyof typeof Ionicons.glyphMap} size={21} color={color} />
      </View>
      <View style={womanSettings.rowCopy}>
        <Text style={womanSettings.rowTitle}>{title}</Text>
        {subtitle ? <Text style={womanSettings.rowSub}>{subtitle}</Text> : null}
        {chips?.length ? (
          <View style={womanSettings.permissionChips}>
            {chips.map((chip: string) => (
              <Text key={chip} style={[womanSettings.permissionChip, chip === 'Mic' && womanSettings.permissionChipWarn]}>{chip}</Text>
            ))}
          </View>
        ) : null}
      </View>
      <Ionicons name="chevron-forward" size={18} color="#CBD5E1" />
    </TouchableOpacity>
  );
}

function ChildSettingsScreen() {
  const router = useRouter();
  const { logout } = useAuthStore();
  const [expandedSafety, setExpandedSafety] = useState<null | 'zones' | 'contacts'>(null);
  const [childSheet, setChildSheet] = useState<null | 'language' | 'textSize'>(null);

  const handleChildSignOut = async () => {
    await logout();
    router.replace('/intro');
  };

  const profileRows = [
    ['Full Name', 'Aarav Sharma'],
    ['Role', 'Child - Protected'],
    ['Guardian', 'Rajesh Sharma (Papa)'],
    ['Co-Guardian', 'Sunita Sharma (Mummy)'],
  ];
  const safetyRows = [
    ['location-outline', '#22C55E', 'My Safe Zones', 'Home, School, Tuition'],
    ['call-outline', '#EF4444', 'Emergency Contacts', '3 contacts on priority list'],
    ['watch-outline', '#F59E0B', 'My Wearables', "Aarav's Watch - Emergency Keychain"],
  ];
  const privacyRows = [
    ['location-outline', '#22C55E', 'Location Permission', 'Enabled', 'Keeps your guardians updated on your whereabouts', true],
    ['mic-outline', '#94A3B8', 'Microphone', 'Not Granted', 'Tap to enable in Settings - helps detect distress sounds', false],
    ['pulse-outline', '#0EA5E9', 'Background Activity', 'Enabled', 'Allows NISCHINT to protect you even when app is closed', true],
  ] as const;
  const notificationRows = [
    ['notifications-outline', '#0EA5E9', 'Safety Check Reminders'],
    ['location-outline', '#22C55E', 'Route Alerts'],
    ['shield-outline', '#F59E0B', 'Guardian Messages'],
  ];

  return (
    <SafeAreaView style={childSettings.safe} edges={['top']}>
      <ScrollView style={childSettings.scroll} contentContainerStyle={childSettings.content} showsVerticalScrollIndicator={false}>
        <View style={childSettings.hero}>
          <View style={childSettings.avatar}>
            <Text style={childSettings.avatarEmoji}>👦</Text>
          </View>
          <View>
            <Text style={childSettings.name}>Aarav</Text>
            <Text style={childSettings.memberPill}>Protected Member</Text>
            <Text style={childSettings.guardianMeta}>Guardian: Papa (Rajesh)</Text>
          </View>
        </View>

        <Text style={childSettings.sectionLabel}>MY PROFILE</Text>
        <View style={childSettings.card}>
          {profileRows.map(([label, value], index) => (
            <View key={label} style={[childSettings.infoRow, index > 0 && childSettings.rowBorder]}>
              <Text style={childSettings.infoLabel}>{label}</Text>
              <Text style={childSettings.infoValue}>{value}</Text>
            </View>
          ))}
        </View>

        <Text style={childSettings.sectionLabel}>MY SAFETY</Text>
        <View style={childSettings.card}>
          <TouchableOpacity activeOpacity={0.78} onPress={() => setExpandedSafety(expandedSafety === 'zones' ? null : 'zones')} style={childSettings.menuRow}>
            <View style={[childSettings.menuIcon, { backgroundColor: '#22C55E14' }]}>
              <Ionicons name="location-outline" size={22} color="#22C55E" />
            </View>
            <View style={childSettings.menuCopy}>
              <Text style={childSettings.menuTitle}>My Safe Zones</Text>
              <Text style={childSettings.menuSub}>Home, School, Tuition</Text>
            </View>
            <Ionicons name={expandedSafety === 'zones' ? 'chevron-down' : 'chevron-forward'} size={18} color="#CBD5E1" />
          </TouchableOpacity>
          {expandedSafety === 'zones' ? (
            <View style={childSettings.expandedPanel}>
              <ChildZoneCard icon="home-outline" color="#22C55E" bg="#F0FDF4" title="Home" subtitle="Sector 21, Pune" />
              <ChildZoneCard icon="business-outline" color="#0B84FF" bg="#EFF6FF" title="School" subtitle="Delhi Public School, Pune" />
              <ChildZoneCard icon="location-outline" color="#F59E0B" bg="#FFF7ED" title="Tuition" subtitle="Agarwal Classes, Camp" />
            </View>
          ) : null}

          <TouchableOpacity activeOpacity={0.78} onPress={() => setExpandedSafety(expandedSafety === 'contacts' ? null : 'contacts')} style={[childSettings.menuRow, childSettings.rowBorder]}>
            <View style={[childSettings.menuIcon, { backgroundColor: '#EF444414' }]}>
              <Ionicons name="call-outline" size={22} color="#EF4444" />
            </View>
            <View style={childSettings.menuCopy}>
              <Text style={childSettings.menuTitle}>Emergency Contacts</Text>
              <Text style={childSettings.menuSub}>3 contacts on priority list</Text>
            </View>
            <Ionicons name={expandedSafety === 'contacts' ? 'chevron-down' : 'chevron-forward'} size={18} color="#CBD5E1" />
          </TouchableOpacity>
          {expandedSafety === 'contacts' ? (
            <View style={childSettings.expandedPanel}>
              <ChildContactCard icon="shield" name="Papa (Rajesh)" role="Primary Guardian" rank="#1" />
              <ChildContactCard emoji="👩" name="Mummy (Sunita)" role="Co-Guardian" rank="#2" />
              <ChildContactCard emoji="👵" name="Dadi (Kamla)" role="Family" rank="#3" />
            </View>
          ) : null}

          <TouchableOpacity activeOpacity={0.78} style={[childSettings.menuRow, childSettings.rowBorder]}>
            <View style={[childSettings.menuIcon, { backgroundColor: '#F59E0B14' }]}>
              <Ionicons name="watch-outline" size={22} color="#F59E0B" />
            </View>
            <View style={childSettings.menuCopy}>
              <Text style={childSettings.menuTitle}>My Wearables</Text>
              <Text style={childSettings.menuSub}>Aarav's Watch - Emergency Keychain</Text>
            </View>
            <Ionicons name="chevron-forward" size={18} color="#CBD5E1" />
          </TouchableOpacity>
        </View>

        <Text style={childSettings.sectionLabel}>PRIVACY (WHAT YOU'VE GRANTED)</Text>
        <View style={childSettings.card}>
          {privacyRows.map(([icon, color, title, status, desc, enabled], index) => (
            <View key={title} style={[childSettings.permissionRow, index > 0 && childSettings.rowBorder]}>
              <View style={[childSettings.menuIcon, { backgroundColor: `${color}14` }]}>
                <Ionicons name={icon as keyof typeof Ionicons.glyphMap} size={22} color={color} />
              </View>
              <View style={childSettings.menuCopy}>
                <Text style={childSettings.menuTitle}>{title}</Text>
                <Text style={[childSettings.permissionState, enabled ? childSettings.enabledText : childSettings.deniedText]}>{status}</Text>
                <Text style={childSettings.permissionDesc}>{desc}</Text>
              </View>
              <Switch value={enabled} disabled trackColor={{ false: '#CBD5E1', true: '#22C55E' }} thumbColor="#FFFFFF" />
            </View>
          ))}
        </View>

        <Text style={childSettings.sectionLabel}>NOTIFICATIONS</Text>
        <View style={childSettings.card}>
          {notificationRows.map(([icon, color, title], index) => (
            <View key={title} style={[childSettings.switchRow, index > 0 && childSettings.rowBorder]}>
              <View style={[childSettings.menuIcon, { backgroundColor: `${color}14` }]}>
                <Ionicons name={icon as keyof typeof Ionicons.glyphMap} size={22} color={color} />
              </View>
              <Text style={childSettings.switchTitle}>{title}</Text>
              <Switch value disabled trackColor={{ false: '#CBD5E1', true: '#22C55E' }} thumbColor="#FFFFFF" />
            </View>
          ))}
        </View>

        <Text style={childSettings.sectionLabel}>ACCESSIBILITY</Text>
        <View style={childSettings.card}>
          <ChildSettingsMenu icon="language-outline" color="#8B5CF6" title="Language" subtitle="English" onPress={() => setChildSheet('language')} />
          <ChildSettingsMenu icon="text-outline" color="#F59E0B" title="Text Size" subtitle="Normal" bordered onPress={() => setChildSheet('textSize')} />
        </View>

        <Text style={childSettings.sectionLabel}>ACCOUNT SECURITY</Text>
        <View style={childSettings.card}>
          <TouchableOpacity activeOpacity={0.82} onPress={handleChildSignOut} style={childSettings.menuRow}>
            <View style={[childSettings.menuIcon, { backgroundColor: '#EF444414' }]}>
              <Ionicons name="log-out-outline" size={22} color="#EF4444" />
            </View>
            <View style={childSettings.menuCopy}>
              <Text style={[childSettings.menuTitle, { color: '#EF4444' }]}>Sign Out</Text>
              <Text style={childSettings.menuSub}>Requires parent approval</Text>
            </View>
            <Ionicons name="lock-closed-outline" size={18} color="#CBD5E1" />
          </TouchableOpacity>
        </View>

        <Text style={childSettings.sectionLabel}>HELP</Text>
        <View style={childSettings.card}>
          <ChildSettingsMenu icon="help-circle-outline" color="#0EA5E9" title="How to use NISCHINT" subtitle="App guide for kids" />
          <ChildSettingsMenu icon="call-outline" color="#22C55E" title="Contact Support" subtitle="Get help from our team" bordered />
        </View>
      </ScrollView>
      <ChildSettingsOptionSheet type={childSheet} onClose={() => setChildSheet(null)} />
    </SafeAreaView>
  );
}

function ChildZoneCard({ icon, color, bg, title, subtitle }: any) {
  return (
    <View style={[childSettings.zoneCard, { backgroundColor: bg, borderColor: `${color}30` }]}>
      <Ionicons name={icon as keyof typeof Ionicons.glyphMap} size={18} color={color} />
      <View>
        <Text style={[childSettings.zoneTitle, { color }]}>{title}</Text>
        <Text style={childSettings.zoneSub}>{subtitle}</Text>
      </View>
    </View>
  );
}

function ChildContactCard({ icon, emoji, name, role, rank }: any) {
  return (
    <View style={childSettings.contactMiniCard}>
      <View style={childSettings.contactMiniIcon}>
        {icon ? <Ionicons name={icon as keyof typeof Ionicons.glyphMap} size={23} color="#0B84FF" /> : <Text style={childSettings.contactEmoji}>{emoji}</Text>}
      </View>
      <View style={{ flex: 1 }}>
        <Text style={childSettings.contactName}>{name}</Text>
        <Text style={childSettings.contactRole}>{role}</Text>
      </View>
      <Text style={childSettings.contactRank}>{rank}</Text>
    </View>
  );
}

function ChildSettingsOptionSheet({ type, onClose }: { type: null | 'language' | 'textSize'; onClose: () => void }) {
  if (!type) return null;
  const options = type === 'language'
    ? ['English', 'Hindi', 'Marathi', 'Gujarati', 'Tamil', 'Telugu']
    : ['Normal', 'Large', 'Extra Large'];

  return (
    <View style={childSettings.sheetLayer}>
      <TouchableOpacity activeOpacity={1} style={childSettings.sheetBackdrop} onPress={onClose} />
      <View style={childSettings.optionSheet}>
        <Text style={childSettings.optionTitle}>{type === 'language' ? 'Choose Language' : 'Text Size'}</Text>
        {options.map((option, index) => (
          <TouchableOpacity key={option} activeOpacity={0.82} onPress={onClose} style={[childSettings.optionRow, index === 0 && childSettings.optionSelected]}>
            <Text style={childSettings.optionText}>{option}</Text>
          </TouchableOpacity>
        ))}
      </View>
    </View>
  );
}

function ChildSignOutLockedSheet({ visible, onClose }: { visible: boolean; onClose: () => void }) {
  if (!visible) return null;
  return (
    <View style={childSettings.sheetLayer}>
      <TouchableOpacity activeOpacity={1} style={childSettings.lockBackdrop} onPress={onClose} />
      <View style={childSettings.lockSheet}>
        <View style={childSettings.lockIconBox}>
          <Ionicons name="lock-closed-outline" size={42} color="#EF4444" />
        </View>
        <Text style={childSettings.lockTitle}>Sign Out Locked</Text>
        <Text style={childSettings.lockCopy}>Ask your parent to log you out safely.</Text>
        <Text style={childSettings.lockSubcopy}>This keeps your account protected at all times.</Text>
        <TouchableOpacity activeOpacity={0.86} onPress={onClose} style={childSettings.gotItBtn}>
          <Text style={childSettings.gotItText}>Got it!</Text>
        </TouchableOpacity>
        <TouchableOpacity activeOpacity={0.82} onPress={onClose} style={childSettings.cancelLockedBtn}>
          <Text style={childSettings.cancelLockedText}>Cancel</Text>
        </TouchableOpacity>
      </View>
    </View>
  );
}

function ChildSettingsMenu({ icon, color, title, subtitle, bordered, onPress }: any) {
  return (
    <TouchableOpacity activeOpacity={0.78} onPress={onPress} style={[childSettings.menuRow, bordered && childSettings.rowBorder]}>
      <View style={[childSettings.menuIcon, { backgroundColor: `${color}14` }]}>
        <Ionicons name={icon as keyof typeof Ionicons.glyphMap} size={22} color={color} />
      </View>
      <View style={childSettings.menuCopy}>
        <Text style={childSettings.menuTitle}>{title}</Text>
        <Text style={childSettings.menuSub}>{subtitle}</Text>
      </View>
      <Ionicons name="chevron-forward" size={18} color="#CBD5E1" />
    </TouchableOpacity>
  );
}

const womanSettings = StyleSheet.create({
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
  scroll: { flex: 1 },
  content: { paddingBottom: 96 },
  brandRow: { backgroundColor: '#FFFFFF', flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 20, paddingTop: 26, paddingBottom: 14 },
  brandLeft: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  brandIcon: { width: 30, height: 30, borderRadius: 15, backgroundColor: '#0EA5E9', alignItems: 'center', justifyContent: 'center' },
  brandText: { color: '#020817', fontSize: 16, fontWeight: '900', letterSpacing: 2 },
  version: { color: '#94A3B8', fontSize: 12, fontWeight: '800' },
  profileCard: { marginHorizontal: 20, marginTop: 8, marginBottom: 18, borderRadius: 18, backgroundColor: '#F6F9FD', minHeight: 98, flexDirection: 'row', alignItems: 'center', padding: 14 },
  avatarBox: { width: 68, height: 68, borderRadius: 18, alignItems: 'center', justifyContent: 'center' },
  avatarText: { color: '#FFFFFF', fontSize: 34, fontWeight: '900' },
  profileCopy: { flex: 1, marginLeft: 14 },
  profileName: { color: '#06122A', fontSize: 22, fontWeight: '900' },
  profileMeta: { color: '#53657E', fontSize: 15, fontWeight: '700', marginTop: 2 },
  protectedText: { color: '#16A34A', fontSize: 12, fontWeight: '900', marginTop: 6 },
  sectionLabel: { color: '#94A3B8', fontSize: 13, fontWeight: '900', letterSpacing: 1.4, marginTop: 20, marginBottom: 10, paddingHorizontal: 24 },
  card: { marginHorizontal: 20, borderRadius: 18, backgroundColor: '#FFFFFF', overflow: 'hidden', shadowColor: '#0F172A', shadowOpacity: 0.05, shadowOffset: { width: 0, height: 6 }, shadowRadius: 14, elevation: 2 },
  row: { minHeight: 82, flexDirection: 'row', alignItems: 'center', paddingHorizontal: 20 },
  rowBorder: { borderTopWidth: 1, borderTopColor: '#EEF2F7' },
  rowIcon: { width: 44, height: 44, borderRadius: 22, alignItems: 'center', justifyContent: 'center' },
  rowCopy: { flex: 1, marginLeft: 14 },
  rowTitle: { color: '#06122A', fontSize: 18, fontWeight: '900' },
  rowSub: { color: '#53657E', fontSize: 14, marginTop: 3 },
  monitoringCard: { marginHorizontal: 20, minHeight: 128, borderRadius: 18, backgroundColor: '#11B7E8', flexDirection: 'row', alignItems: 'center', padding: 20, shadowColor: '#0EA5E9', shadowOpacity: 0.22, shadowOffset: { width: 0, height: 10 }, shadowRadius: 18, elevation: 3 },
  monitoringIcon: { width: 50, height: 50, borderRadius: 25, backgroundColor: '#FFFFFF24', alignItems: 'center', justifyContent: 'center' },
  monitoringCopy: { flex: 1, marginLeft: 14 },
  monitoringTitle: { color: '#FFFFFF', fontSize: 18, fontWeight: '900' },
  monitoringSub: { color: '#DDFBFF', fontSize: 13, marginTop: 4 },
  chipRow: { flexDirection: 'row', gap: 7, marginTop: 12, flexWrap: 'wrap' },
  blueChip: { color: '#FFFFFF', fontSize: 12, fontWeight: '900', paddingHorizontal: 11, paddingVertical: 5, borderRadius: 13, backgroundColor: '#FFFFFF22', overflow: 'hidden' },
  permissionChips: { flexDirection: 'row', gap: 6, marginTop: 8, flexWrap: 'wrap' },
  permissionChip: { color: '#16A34A', fontSize: 11, fontWeight: '900', paddingHorizontal: 9, paddingVertical: 3, borderRadius: 10, backgroundColor: '#DCFCE7', overflow: 'hidden' },
  permissionChipWarn: { color: '#EF4444', backgroundColor: '#FEE2E2' },
  logoutCard: { marginHorizontal: 20, minHeight: 82, borderRadius: 18, backgroundColor: '#FFFFFF', flexDirection: 'row', alignItems: 'center', paddingHorizontal: 20, shadowColor: '#0F172A', shadowOpacity: 0.05, shadowOffset: { width: 0, height: 6 }, shadowRadius: 14, elevation: 2 },
  logoutTitle: { color: '#EF4444', fontSize: 18, fontWeight: '900' },
  footer: { color: '#CBD5E1', fontSize: 12, fontWeight: '800', textAlign: 'center', marginTop: 24 },
  detailTitleBar: { height: 84, backgroundColor: '#FFFFFF', borderBottomWidth: 1, borderBottomColor: '#E2E8F0', flexDirection: 'row', alignItems: 'center', paddingHorizontal: 20, gap: 14 },
  detailTitle: { color: '#07111F', fontSize: 22, fontWeight: '900' },
  detailContent: { paddingTop: 22, paddingBottom: 118 },
  profileHero: { alignItems: 'center', paddingVertical: 28 },
  profileAvatarLarge: { width: 100, height: 100, borderRadius: 22, alignItems: 'center', justifyContent: 'center' },
  profileAvatarText: { color: '#FFFFFF', fontSize: 40, fontWeight: '900' },
  profileHeroName: { color: '#07111F', fontSize: 23, fontWeight: '900', marginTop: 18 },
  profileHeroMeta: { color: '#53657E', fontSize: 15, fontWeight: '700', marginTop: 4 },
  detailCard: { marginHorizontal: 20, borderRadius: 18, backgroundColor: '#FFFFFF', paddingHorizontal: 20, paddingVertical: 16, shadowColor: '#0F172A', shadowOpacity: 0.05, shadowOffset: { width: 0, height: 6 }, shadowRadius: 14, elevation: 2 },
  profileInfoRow: { minHeight: 76, justifyContent: 'center' },
  profileInfoBorder: { borderTopWidth: 1, borderTopColor: '#EEF2F7' },
  infoLabel: { color: '#94A3B8', fontSize: 13, fontWeight: '900', letterSpacing: 1 },
  infoValue: { color: '#07111F', fontSize: 18, fontWeight: '900', marginTop: 8 },
  managedNotice: { minHeight: 78, borderRadius: 16, backgroundColor: '#FEF3C7', marginHorizontal: 20, marginTop: 16, flexDirection: 'row', alignItems: 'center', gap: 14, paddingHorizontal: 20 },
  managedNoticeText: { flex: 1, color: '#92400E', fontSize: 15, fontWeight: '800', lineHeight: 24 },
  familyNote: { color: '#8A9AB4', fontSize: 14, fontWeight: '700', marginHorizontal: 20, marginBottom: 18 },
  guardianPersonCard: { minHeight: 86, borderRadius: 17, backgroundColor: '#FFFFFF', marginHorizontal: 20, marginBottom: 14, flexDirection: 'row', alignItems: 'center', paddingHorizontal: 20, shadowColor: '#0F172A', shadowOpacity: 0.04, shadowOffset: { width: 0, height: 5 }, shadowRadius: 12, elevation: 1 },
  guardianInitial: { width: 50, height: 50, borderRadius: 16, alignItems: 'center', justifyContent: 'center', marginRight: 16 },
  guardianInitialText: { color: '#FFFFFF', fontSize: 22, fontWeight: '900' },
  guardianName: { color: '#07111F', fontSize: 18, fontWeight: '900' },
  guardianSub: { color: '#53657E', fontSize: 14, fontWeight: '700', marginTop: 4 },
  protectedNotice: { minHeight: 78, borderRadius: 18, backgroundColor: '#DCFCE7', marginHorizontal: 20, marginTop: 2, flexDirection: 'row', alignItems: 'center', gap: 14, paddingHorizontal: 20 },
  protectedNoticeText: { flex: 1, color: '#15803D', fontSize: 15, fontWeight: '800', lineHeight: 22 },
  detailTabs: { height: 62, backgroundColor: '#FFFFFF', borderTopWidth: 1, borderBottomWidth: 1, borderColor: '#E2E8F0', flexDirection: 'row', alignItems: 'flex-end', marginBottom: 18 },
  detailTab: { flex: 1, height: 56, alignItems: 'center', justifyContent: 'center', borderBottomWidth: 2, borderBottomColor: 'transparent' },
  detailTabActive: { borderBottomColor: '#0B84FF' },
  detailTabText: { color: '#53657E', fontSize: 16, fontWeight: '900' },
  detailTabTextActive: { color: '#0B84FF' },
  monitorDetailRow: { minHeight: 80, flexDirection: 'row', alignItems: 'center' },
  monitorDetailTitle: { color: '#07111F', fontSize: 18, fontWeight: '900' },
  monitorDetailSub: { color: '#53657E', fontSize: 14, fontWeight: '700', marginTop: 6 },
  stateBadge: { color: '#15803D', fontSize: 12, fontWeight: '900', backgroundColor: '#DCFCE7', paddingHorizontal: 10, paddingVertical: 7, borderRadius: 13, overflow: 'hidden' },
  stateOff: { color: '#64748B', backgroundColor: '#EEF2F7' },
  deviceDetailCard: { marginHorizontal: 20, marginBottom: 14, borderRadius: 18, backgroundColor: '#FFFFFF', padding: 20, shadowColor: '#0F172A', shadowOpacity: 0.05, shadowOffset: { width: 0, height: 6 }, shadowRadius: 14, elevation: 2 },
  deviceTitleRow: { flexDirection: 'row', alignItems: 'center', gap: 14, marginBottom: 14 },
  deviceTitle: { color: '#07111F', fontSize: 19, fontWeight: '900' },
  deviceSub: { color: '#16A34A', fontSize: 13, fontWeight: '800', marginTop: 4 },
  deviceOff: { color: '#94A3B8' },
  batteryLine: { height: 7, borderRadius: 4, backgroundColor: '#E2E8F0', overflow: 'hidden', marginTop: 4 },
  batteryFill: { height: '100%', backgroundColor: '#22C55E' },
  batteryText: { color: '#07111F', fontSize: 13, fontWeight: '900', textAlign: 'right', marginTop: -18, marginBottom: 18 },
  deviceActionRow: { minHeight: 46, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  deviceActionText: { color: '#07111F', fontSize: 17, fontWeight: '900' },
  pairButton: { flex: 1, color: '#0B84FF', fontSize: 16, fontWeight: '900', borderWidth: 1, borderStyle: 'dashed', borderColor: '#B7D7FA', borderRadius: 15, textAlign: 'center', paddingVertical: 11, overflow: 'hidden' },
  addDeviceDashed: { marginHorizontal: 20, minHeight: 64, borderRadius: 16, borderWidth: 1.5, borderStyle: 'dashed', borderColor: '#B7D7FA', alignItems: 'center', justifyContent: 'center' },
  addDeviceText: { color: '#64748B', fontSize: 17, fontWeight: '900' },
  permissionDetailCard: { marginHorizontal: 20, marginBottom: 14, borderRadius: 18, backgroundColor: '#FFFFFF', padding: 20, shadowColor: '#0F172A', shadowOpacity: 0.05, shadowOffset: { width: 0, height: 6 }, shadowRadius: 14, elevation: 2 },
  permissionHead: { flexDirection: 'row', alignItems: 'center', gap: 14, marginBottom: 12 },
  permissionTitle: { flex: 1, color: '#07111F', fontSize: 18, fontWeight: '900' },
  permissionStatePill: { color: '#15803D', fontSize: 12, fontWeight: '900', backgroundColor: '#DCFCE7', borderRadius: 14, paddingHorizontal: 11, paddingVertical: 7, overflow: 'hidden' },
  permissionDenied: { color: '#DC2626', backgroundColor: '#FEE2E2' },
  permissionOptional: { color: '#B45309', backgroundColor: '#FEF3C7' },
  permissionBullet: { color: '#53657E', fontSize: 14, fontWeight: '700', marginLeft: 58, marginBottom: 7 },
  systemSettingsBtn: { color: '#0B84FF', fontSize: 15, fontWeight: '900', backgroundColor: '#EAF4FF', borderRadius: 16, textAlign: 'center', paddingVertical: 12, marginTop: 8, overflow: 'hidden' },
  privacyList: { gap: 12 },
  notificationRow: { minHeight: 76, flexDirection: 'row', alignItems: 'center' },
  alwaysOn: { color: '#0B84FF', fontSize: 12, fontWeight: '900', backgroundColor: '#EAF4FF', borderRadius: 13, paddingHorizontal: 10, paddingVertical: 7, overflow: 'hidden' },
});

const childSettings = StyleSheet.create({
  safe: { flex: 1, backgroundColor: '#F3F7FB' },
  scroll: { flex: 1 },
  content: { paddingBottom: 108 },
  hero: { backgroundColor: '#18345A', paddingHorizontal: 36, paddingTop: 76, paddingBottom: 34, flexDirection: 'row', alignItems: 'center', gap: 16 },
  avatar: { width: 70, height: 70, borderRadius: 18, alignItems: 'center', justifyContent: 'center', backgroundColor: '#E8F0FF' },
  avatarEmoji: { fontSize: 31 },
  name: { color: '#FFFFFF', fontSize: 24, fontWeight: '900' },
  memberPill: { alignSelf: 'flex-start', overflow: 'hidden', borderRadius: 12, backgroundColor: '#0A69BB', color: '#AAD4FF', paddingHorizontal: 10, paddingVertical: 5, fontSize: 13, fontWeight: '900', marginTop: 7 },
  guardianMeta: { color: '#8EA0BB', fontSize: 14, fontWeight: '800', marginTop: 8 },
  sectionLabel: { color: '#60708A', fontSize: 14, fontWeight: '900', letterSpacing: 1.6, marginTop: 22, marginBottom: 12, paddingHorizontal: 30 },
  card: { marginHorizontal: 30, borderRadius: 16, backgroundColor: '#FFFFFF', overflow: 'hidden', shadowColor: '#0F172A', shadowOpacity: 0.06, shadowOffset: { width: 0, height: 8 }, shadowRadius: 18, elevation: 2 },
  rowBorder: { borderTopWidth: 1, borderTopColor: '#EEF2F7' },
  infoRow: { minHeight: 56, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 20, gap: 14 },
  infoLabel: { color: '#53657E', fontSize: 15, fontWeight: '700' },
  infoValue: { flex: 1, color: '#06122A', fontSize: 16, fontWeight: '900', textAlign: 'right' },
  menuRow: { minHeight: 80, flexDirection: 'row', alignItems: 'center', paddingHorizontal: 18, gap: 14 },
  menuIcon: { width: 46, height: 46, borderRadius: 23, alignItems: 'center', justifyContent: 'center' },
  menuCopy: { flex: 1 },
  menuTitle: { color: '#06122A', fontSize: 17, fontWeight: '900' },
  menuSub: { color: '#53657E', fontSize: 14, fontWeight: '600', marginTop: 4 },
  permissionRow: { minHeight: 118, flexDirection: 'row', alignItems: 'center', paddingHorizontal: 18, gap: 14 },
  permissionState: { fontSize: 13, fontWeight: '900', marginTop: 4 },
  enabledText: { color: '#16A34A' },
  deniedText: { color: '#EF4444' },
  permissionDesc: { color: '#8A98B3', fontSize: 14, fontWeight: '600', lineHeight: 22, marginTop: 10 },
  switchRow: { minHeight: 80, flexDirection: 'row', alignItems: 'center', paddingHorizontal: 18, gap: 14 },
  switchTitle: { flex: 1, color: '#06122A', fontSize: 17, fontWeight: '900' },
  expandedPanel: { paddingHorizontal: 20, paddingBottom: 16, gap: 10 },
  zoneCard: { minHeight: 70, borderRadius: 16, borderWidth: 1, flexDirection: 'row', alignItems: 'center', gap: 14, paddingHorizontal: 16 },
  zoneTitle: { fontSize: 16, fontWeight: '900' },
  zoneSub: { color: '#53657E', fontSize: 14, fontWeight: '700', marginTop: 4 },
  contactMiniCard: { minHeight: 72, borderRadius: 16, backgroundColor: '#F8FAFC', flexDirection: 'row', alignItems: 'center', gap: 14, paddingHorizontal: 16 },
  contactMiniIcon: { width: 44, height: 44, borderRadius: 22, backgroundColor: '#EEF2F7', alignItems: 'center', justifyContent: 'center' },
  contactEmoji: { fontSize: 23 },
  contactName: { color: '#06122A', fontSize: 16, fontWeight: '900' },
  contactRole: { color: '#53657E', fontSize: 14, fontWeight: '700', marginTop: 4 },
  contactRank: { color: '#2563EB', fontSize: 13, fontWeight: '900', backgroundColor: '#EFF6FF', paddingHorizontal: 10, paddingVertical: 7, borderRadius: 14, overflow: 'hidden' },
  sheetLayer: { ...StyleSheet.absoluteFillObject, justifyContent: 'flex-end' },
  sheetBackdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: 'rgba(15,23,42,0.22)' },
  optionSheet: { backgroundColor: '#FFFFFF', paddingHorizontal: 26, paddingTop: 30, paddingBottom: 30, borderTopLeftRadius: 2, borderTopRightRadius: 2 },
  optionTitle: { color: '#07111F', fontSize: 22, fontWeight: '900', marginBottom: 20 },
  optionRow: { minHeight: 56, borderRadius: 14, backgroundColor: '#F8FAFC', justifyContent: 'center', paddingHorizontal: 20, marginBottom: 11 },
  optionSelected: { backgroundColor: '#EFF6FF', borderWidth: 1, borderColor: '#BFDBFE' },
  optionText: { color: '#07111F', fontSize: 16, fontWeight: '900' },
  lockBackdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: 'rgba(15,23,42,0.60)' },
  lockSheet: { backgroundColor: '#FFFFFF', alignItems: 'center', paddingTop: 30 },
  lockIconBox: { width: 80, height: 80, borderRadius: 22, backgroundColor: '#FEE2E2', alignItems: 'center', justifyContent: 'center', marginBottom: 22 },
  lockTitle: { color: '#07111F', fontSize: 20, fontWeight: '900' },
  lockCopy: { color: '#53657E', fontSize: 17, fontWeight: '700', marginTop: 16 },
  lockSubcopy: { color: '#94A3B8', fontSize: 14, fontWeight: '800', marginTop: 8, marginBottom: 28 },
  gotItBtn: { width: '100%', height: 58, backgroundColor: '#18345A', alignItems: 'center', justifyContent: 'center' },
  gotItText: { color: '#FFFFFF', fontSize: 17, fontWeight: '900' },
  cancelLockedBtn: { width: '100%', height: 68, alignItems: 'center', justifyContent: 'center', backgroundColor: '#FFFFFF' },
  cancelLockedText: { color: '#94A3B8', fontSize: 16, fontWeight: '900' },
});

const subStyles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: '#F5F7FB' },
  header: { minHeight: 130, backgroundColor: '#FFFFFF', borderBottomWidth: 1, borderBottomColor: '#E2E8F0', flexDirection: 'row', alignItems: 'center', gap: 14, paddingHorizontal: 20, paddingTop: 28 },
  backBtn: { width: 46, height: 46, borderRadius: 23, backgroundColor: '#F1F5F9', alignItems: 'center', justifyContent: 'center' },
  headerTitle: { color: '#07111F', fontSize: 26, fontWeight: '900' },
  scroll: { flex: 1 },
  content: { paddingHorizontal: 28, paddingTop: 26, paddingBottom: 118 },
  currentPlan: { borderRadius: 17, padding: 24, minHeight: 216, overflow: 'hidden' },
  planLabel: { color: 'rgba(255,255,255,0.75)', fontSize: 12, fontWeight: '900', letterSpacing: 2 },
  planName: { color: '#FFFFFF', fontSize: 26, fontWeight: '900', marginTop: 12 },
  planMeta: { color: 'rgba(255,255,255,0.9)', fontSize: 15, fontWeight: '800', marginTop: 4 },
  bigPrice: { color: '#FFFFFF', fontSize: 38, fontWeight: '900', marginTop: 18 },
  month: { fontSize: 16, fontWeight: '800' },
  planFoot: { flexDirection: 'row', justifyContent: 'space-between', gap: 14, marginTop: 8 },
  planSmall: { color: 'rgba(255,255,255,0.72)', fontSize: 12, fontWeight: '800' },
  sectionLabel: { color: '#607084', fontSize: 15, fontWeight: '900', letterSpacing: 1.3, marginTop: 26, marginBottom: 12 },
  card: { borderRadius: 17, backgroundColor: '#FFFFFF', overflow: 'hidden', shadowColor: '#0F172A', shadowOpacity: 0.06, shadowOffset: { width: 0, height: 8 }, shadowRadius: 18, elevation: 2 },
  memberRow: { minHeight: 82, flexDirection: 'row', alignItems: 'center', gap: 16, paddingHorizontal: 20 },
  memberEmoji: { fontSize: 27 },
  memberName: { color: '#07111F', fontSize: 18, fontWeight: '900' },
  memberRole: { color: '#52647C', fontSize: 15, fontWeight: '700', marginTop: 3 },
  memberBadge: { color: '#2563EB', fontSize: 12, fontWeight: '900', paddingHorizontal: 11, paddingVertical: 6, borderRadius: 13, backgroundColor: '#EFF6FF', overflow: 'hidden' },
  memberBadgePurple: { color: '#8B5CF6', backgroundColor: '#F3E8FF' },
  rowBorder: { borderTopWidth: 1, borderTopColor: '#EEF2F7' },
  addMemberCard: { borderRadius: 17, backgroundColor: '#FFFFFF', padding: 20, shadowColor: '#0F172A', shadowOpacity: 0.06, shadowOffset: { width: 0, height: 8 }, shadowRadius: 18, elevation: 2 },
  addMemberTitle: { color: '#07111F', fontSize: 17, fontWeight: '900' },
  addMemberSub: { color: '#64748B', fontSize: 15, fontWeight: '700', marginTop: 7, marginBottom: 16 },
  addProtectedBtn: { minHeight: 56, borderRadius: 15, backgroundColor: '#10BDF2', flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 10 },
  addProtectedText: { color: '#FFFFFF', fontSize: 18, fontWeight: '900' },
  actionRow: { minHeight: 82, flexDirection: 'row', alignItems: 'center', gap: 16, paddingHorizontal: 18 },
  actionIcon: { width: 44, height: 44, borderRadius: 22, alignItems: 'center', justifyContent: 'center' },
  actionTitle: { color: '#07111F', fontSize: 18, fontWeight: '900' },
  dangerTitle: { color: '#EF4444' },
  actionSub: { color: '#52647C', fontSize: 15, fontWeight: '700', marginTop: 4 },
});

const sheetStyles = StyleSheet.create({
  layer: { ...StyleSheet.absoluteFillObject, justifyContent: 'flex-end' },
  backdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: 'rgba(15, 23, 42, 0.48)' },
  avoider: { justifyContent: 'flex-end' },
  sheet: { borderTopLeftRadius: 24, borderTopRightRadius: 24, backgroundColor: '#FFFFFF', paddingHorizontal: 24, paddingTop: 8, paddingBottom: 28, minHeight: 410 },
  transferSheet: { minHeight: 620 },
  contactSheet: { minHeight: 466 },
  handle: { alignSelf: 'center', width: 50, height: 5, borderRadius: 3, backgroundColor: '#E2E8F0', marginBottom: 16 },
  centerTitle: { color: '#07111F', fontSize: 21, fontWeight: '900', textAlign: 'center' },
  centerSub: { color: '#52647C', fontSize: 15, fontWeight: '700', textAlign: 'center', marginTop: 6, marginBottom: 20 },
  memberGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 14 },
  memberTypeCard: { width: '48%', minHeight: 130, borderRadius: 16, borderWidth: 1.4, borderColor: '#DCE5EF', backgroundColor: '#FFFFFF', padding: 16, justifyContent: 'center' },
  memberTypeSelected: { borderColor: '#0B84FF', backgroundColor: '#F0F8FF' },
  memberTypeEmoji: { fontSize: 27, marginBottom: 10 },
  memberTypeTitle: { color: '#07111F', fontSize: 18, fontWeight: '900' },
  memberTypeSub: { color: '#52647C', fontSize: 13, fontWeight: '700', lineHeight: 18, marginTop: 5 },
  primaryBtn: { minHeight: 60, borderRadius: 17, backgroundColor: '#12BDF2', alignItems: 'center', justifyContent: 'center', marginTop: 20 },
  disabledBtn: { backgroundColor: '#CBD5E1' },
  primaryText: { color: '#FFFFFF', fontSize: 18, fontWeight: '900' },
  pricePanel: { minHeight: 108, borderRadius: 17, backgroundColor: '#F5F7FB', alignItems: 'center', justifyContent: 'center', marginTop: 8, marginBottom: 20 },
  priceLabel: { color: '#64748B', fontSize: 15, fontWeight: '700', marginBottom: 8 },
  priceBig: { color: '#0B84FF', fontSize: 40, fontWeight: '900' },
  priceSmall: { color: '#52647C', fontSize: 18, fontWeight: '700' },
  inviteActions: { flexDirection: 'row', gap: 14 },
  outlineBlueBtn: { flex: 1, minHeight: 56, borderRadius: 16, borderWidth: 1.5, borderColor: '#0B84FF', alignItems: 'center', justifyContent: 'center', flexDirection: 'row', gap: 8, backgroundColor: '#FFFFFF' },
  outlineBlueText: { color: '#0B84FF', fontSize: 16, fontWeight: '900' },
  compactPrimaryBtn: { flex: 1, minHeight: 56, borderRadius: 16, backgroundColor: '#12BDF2', alignItems: 'center', justifyContent: 'center', flexDirection: 'row', gap: 8 },
  paymentPanel: { borderRadius: 17, backgroundColor: '#F5F7FB', padding: 20, gap: 14, marginTop: 4 },
  paymentRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  paymentLabel: { color: '#52647C', fontSize: 16, fontWeight: '700' },
  paymentAmount: { color: '#07111F', fontSize: 17, fontWeight: '900' },
  paymentNotice: { minHeight: 46, borderRadius: 14, backgroundColor: '#FFF7ED', flexDirection: 'row', alignItems: 'center', gap: 8, paddingHorizontal: 14, marginTop: 18 },
  paymentNoticeText: { flex: 1, color: '#A24E08', fontSize: 13, fontWeight: '700' },
  payBtn: { minHeight: 60, borderRadius: 17, backgroundColor: '#35D06F', alignItems: 'center', justifyContent: 'center', marginTop: 20 },
  memberQrBox: { alignSelf: 'center', width: 210, height: 210, borderRadius: 24, borderWidth: 1, borderColor: '#D8E6F6', backgroundColor: '#FFFFFF', alignItems: 'center', justifyContent: 'center', marginTop: 4, shadowColor: '#0B84FF', shadowOpacity: 0.14, shadowOffset: { width: 0, height: 10 }, shadowRadius: 22, elevation: 3 },
  memberCodeRow: { flexDirection: 'row', justifyContent: 'center', gap: 8, marginTop: 20, marginBottom: 8 },
  memberCodeBox: { width: 48, height: 56, borderRadius: 14, borderWidth: 1.5, borderColor: '#D8E1EC', backgroundColor: '#F8FAFC', alignItems: 'center', justifyContent: 'center' },
  memberCodeText: { color: '#07111F', fontSize: 23, fontWeight: '900' },
  inviteCopy: { color: '#52647C', fontSize: 15, fontWeight: '700', lineHeight: 22, textAlign: 'center', marginTop: 18, paddingHorizontal: 10 },
  plainBtn: { minHeight: 48, alignItems: 'center', justifyContent: 'center', marginTop: 14 },
  plainText: { color: '#52647C', fontSize: 17, fontWeight: '800' },
  bluePlainText: { color: '#0B84FF', fontSize: 17, fontWeight: '900' },
  sheetTitleRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 },
  sheetTitle: { color: '#07111F', fontSize: 22, fontWeight: '900' },
  leftSub: { color: '#52647C', fontSize: 15, fontWeight: '700', marginTop: 6, marginBottom: 24 },
  contactGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 14 },
  contactTypeCard: { width: '48%', minHeight: 58, borderRadius: 14, borderWidth: 1.3, borderColor: '#DCE5EF', justifyContent: 'center', paddingHorizontal: 16, backgroundColor: '#FFFFFF' },
  contactTypeSelected: { borderColor: '#0B84FF', backgroundColor: '#EFF6FF' },
  contactTypeText: { color: '#07111F', fontSize: 16, fontWeight: '900' },
  invoiceRow: { minHeight: 86, flexDirection: 'row', alignItems: 'center', gap: 14 },
  invoiceBorder: { borderTopWidth: 1, borderTopColor: '#EEF2F7' },
  invoiceId: { color: '#07111F', fontSize: 18, fontWeight: '900' },
  invoiceDate: { color: '#52647C', fontSize: 14, fontWeight: '700', marginTop: 3 },
  invoiceAmount: { color: '#07111F', fontSize: 18, fontWeight: '900' },
  paidPill: { color: '#16A34A', fontSize: 13, fontWeight: '900', paddingHorizontal: 11, paddingVertical: 6, borderRadius: 13, backgroundColor: '#DCFCE7', overflow: 'hidden' },
  warningIcon: { alignSelf: 'center', width: 70, height: 70, borderRadius: 35, backgroundColor: '#FEF2F2', alignItems: 'center', justifyContent: 'center', marginBottom: 16 },
  crownIcon: { alignSelf: 'center', width: 58, height: 58, borderRadius: 29, backgroundColor: '#FFF7ED', alignItems: 'center', justifyContent: 'center', marginBottom: 16 },
  cancelCopy: { color: '#52647C', fontSize: 18, lineHeight: 29, fontWeight: '700', textAlign: 'center', marginTop: 14 },
  transferCopy: { color: '#52647C', fontSize: 17, lineHeight: 27, fontWeight: '700', textAlign: 'center', marginTop: 14 },
  redStrong: { color: '#EF4444', fontWeight: '900' },
  cancelList: { borderRadius: 16, backgroundColor: '#FEF2F2', padding: 18, marginTop: 24 },
  cancelItem: { color: '#991B1B', fontSize: 15, fontWeight: '700', lineHeight: 26 },
  dangerBtn: { minHeight: 60, borderRadius: 17, backgroundColor: '#EF4444', alignItems: 'center', justifyContent: 'center', marginTop: 20 },
  coParentCard: { minHeight: 74, borderRadius: 15, backgroundColor: '#F8FAFC', flexDirection: 'row', alignItems: 'center', gap: 16, paddingHorizontal: 20, marginTop: 20 },
  coParentEmoji: { fontSize: 27 },
  coParentName: { color: '#07111F', fontSize: 18, fontWeight: '900' },
  coParentSub: { color: '#52647C', fontSize: 15, fontWeight: '700', marginTop: 3 },
  orangeNotice: { minHeight: 66, borderRadius: 15, backgroundColor: '#FFF7ED', flexDirection: 'row', alignItems: 'center', gap: 10, paddingHorizontal: 16, marginTop: 20 },
  orangeNoticeText: { flex: 1, color: '#B45309', fontSize: 14, fontWeight: '700', lineHeight: 21 },
  outlineDangerBtn: { minHeight: 56, borderRadius: 17, borderWidth: 1.4, borderColor: '#EF4444', alignItems: 'center', justifyContent: 'center', marginTop: 20 },
  outlineDangerText: { color: '#EF4444', fontSize: 17, fontWeight: '900' },
  confirmLabel: { color: '#52647C', fontSize: 14, fontWeight: '700', marginTop: 20, marginBottom: 10 },
  confirmStrong: { color: '#07111F', fontWeight: '900' },
  confirmInput: { minHeight: 54, borderRadius: 16, borderWidth: 1.3, borderColor: '#DCE5EF', backgroundColor: '#FFFFFF', paddingHorizontal: 16, color: '#07111F', fontSize: 16, fontWeight: '700' },
});

const profileStyles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: '#F5F7FB' },
  header: { minHeight: 134, backgroundColor: '#FFFFFF', borderBottomWidth: 1, borderBottomColor: '#E2E8F0', flexDirection: 'row', alignItems: 'center', gap: 14, paddingHorizontal: 20, paddingTop: 28 },
  backBtn: { width: 46, height: 46, borderRadius: 23, backgroundColor: '#F1F5F9', alignItems: 'center', justifyContent: 'center' },
  headerTitle: { color: '#07111F', fontSize: 26, fontWeight: '900' },
  scroll: { flex: 1 },
  content: { paddingHorizontal: 20, paddingTop: 26, paddingBottom: 122 },
  heroCard: { minHeight: 270, borderRadius: 18, backgroundColor: '#FFFFFF', alignItems: 'center', justifyContent: 'center', paddingVertical: 24, marginBottom: 16, shadowColor: '#0F172A', shadowOpacity: 0.06, shadowOffset: { width: 0, height: 8 }, shadowRadius: 18, elevation: 2 },
  avatar: { width: 100, height: 100, borderRadius: 50, alignItems: 'center', justifyContent: 'center', marginBottom: 18 },
  avatarLetter: { color: '#FFFFFF', fontSize: 38, fontWeight: '900' },
  name: { color: '#07111F', fontSize: 21, fontWeight: '900' },
  role: { color: '#52647C', fontSize: 15, fontWeight: '700', marginTop: 8 },
  photoBtn: { minHeight: 38, borderRadius: 19, borderWidth: 1, borderColor: '#0B84FF', alignItems: 'center', justifyContent: 'center', paddingHorizontal: 22, marginTop: 16 },
  photoBtnText: { color: '#0B84FF', fontSize: 14, fontWeight: '900' },
  infoCard: { minHeight: 84, borderRadius: 17, backgroundColor: '#FFFFFF', justifyContent: 'center', paddingHorizontal: 20, marginBottom: 14, shadowColor: '#0F172A', shadowOpacity: 0.05, shadowOffset: { width: 0, height: 8 }, shadowRadius: 18, elevation: 2 },
  infoLabel: { color: '#607084', fontSize: 12, fontWeight: '900', letterSpacing: 1.2, marginBottom: 10 },
  infoValue: { color: '#07111F', fontSize: 18, fontWeight: '900' },
  saveBtn: { minHeight: 60, borderRadius: 17, backgroundColor: '#12BDF2', alignItems: 'center', justifyContent: 'center', marginTop: 2 },
  saveText: { color: '#FFFFFF', fontSize: 18, fontWeight: '900' },
});

const familyCircleStyles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: '#F5F7FB' },
  header: { minHeight: 134, backgroundColor: '#FFFFFF', borderBottomWidth: 1, borderBottomColor: '#E2E8F0', flexDirection: 'row', alignItems: 'center', gap: 14, paddingHorizontal: 20, paddingTop: 28 },
  backBtn: { width: 46, height: 46, borderRadius: 23, backgroundColor: '#F1F5F9', alignItems: 'center', justifyContent: 'center' },
  headerTitle: { color: '#07111F', fontSize: 26, fontWeight: '900' },
  scroll: { flex: 1 },
  content: { paddingHorizontal: 20, paddingTop: 26, paddingBottom: 122 },
  sectionLabel: { color: '#607084', fontSize: 15, fontWeight: '900', letterSpacing: 1.2, marginBottom: 12, marginLeft: 4, marginTop: 10 },
  card: { borderRadius: 17, backgroundColor: '#FFFFFF', overflow: 'hidden', marginBottom: 22, shadowColor: '#0F172A', shadowOpacity: 0.06, shadowOffset: { width: 0, height: 8 }, shadowRadius: 18, elevation: 2 },
  memberRow: { minHeight: 82, flexDirection: 'row', alignItems: 'center', gap: 16, paddingHorizontal: 20 },
  rowBorder: { borderTopWidth: 1, borderTopColor: '#EEF2F7' },
  memberAvatar: { width: 44, height: 44, borderRadius: 22, backgroundColor: '#EAF4FF', alignItems: 'center', justifyContent: 'center' },
  memberAvatarPurple: { backgroundColor: '#F3E8FF' },
  memberEmoji: { fontSize: 23 },
  memberName: { color: '#07111F', fontSize: 18, fontWeight: '900' },
  memberRole: { color: '#52647C', fontSize: 15, fontWeight: '700', marginTop: 3 },
  memberBadge: { color: '#2563EB', fontSize: 12, fontWeight: '900', paddingHorizontal: 11, paddingVertical: 6, borderRadius: 13, backgroundColor: '#EFF6FF', overflow: 'hidden' },
  memberBadgePurple: { color: '#8B5CF6', backgroundColor: '#F3E8FF' },
  actionRow: { minHeight: 84, flexDirection: 'row', alignItems: 'center', gap: 16, paddingHorizontal: 20 },
  actionIcon: { width: 44, height: 44, borderRadius: 22, alignItems: 'center', justifyContent: 'center' },
  actionTitle: { color: '#07111F', fontSize: 18, fontWeight: '900' },
  dangerText: { color: '#EF4444' },
  actionSub: { color: '#52647C', fontSize: 15, fontWeight: '700', marginTop: 4 },
  inviteLayer: { ...StyleSheet.absoluteFillObject, justifyContent: 'flex-end' },
  inviteBackdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: 'rgba(15,23,42,0.42)' },
  inviteSheet: { borderTopLeftRadius: 24, borderTopRightRadius: 24, backgroundColor: '#FFFFFF', paddingHorizontal: 22, paddingTop: 10, paddingBottom: 28, minHeight: 520 },
  sheetHandle: { alignSelf: 'center', width: 48, height: 5, borderRadius: 3, backgroundColor: '#E2E8F0', marginBottom: 18 },
  inviteHead: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12, marginBottom: 18 },
  inviteTitle: { color: '#07111F', fontSize: 21, fontWeight: '900' },
  inviteSub: { color: '#64748B', fontSize: 14, fontWeight: '700', marginTop: 5 },
  inviteClose: { width: 42, height: 42, borderRadius: 21, backgroundColor: '#F1F5F9', alignItems: 'center', justifyContent: 'center' },
  inviteTabs: { height: 54, borderRadius: 17, backgroundColor: '#F1F5F9', flexDirection: 'row', padding: 5, marginBottom: 14 },
  inviteTab: { flex: 1, borderRadius: 13, alignItems: 'center', justifyContent: 'center' },
  inviteTabActive: { backgroundColor: '#0B8FF0' },
  inviteTabText: { color: '#607084', fontSize: 15, fontWeight: '900' },
  inviteTabTextActive: { color: '#FFFFFF' },
  timerPill: { alignSelf: 'center', minHeight: 36, borderRadius: 18, backgroundColor: '#EAF4FF', flexDirection: 'row', alignItems: 'center', gap: 7, paddingHorizontal: 14, marginBottom: 18 },
  timerText: { color: '#0B84FF', fontSize: 14, fontWeight: '900' },
  qrWrap: { alignItems: 'center' },
  qrBox: { width: 210, height: 210, borderRadius: 24, backgroundColor: '#FFFFFF', alignItems: 'center', justifyContent: 'center', borderWidth: 1, borderColor: '#D8E6F6', shadowColor: '#0B8FF0', shadowOpacity: 0.14, shadowOffset: { width: 0, height: 10 }, shadowRadius: 22, elevation: 3 },
  qrGrid: { width: 152, height: 152, flexDirection: 'row', flexWrap: 'wrap', gap: 5 },
  qrCell: { width: 14, height: 14, borderRadius: 3, backgroundColor: '#EAF4FF' },
  qrCellFilled: { backgroundColor: '#0F172A' },
  qrCorner: { position: 'absolute', width: 34, height: 34, borderColor: '#22C55E' },
  qrCornerTopLeft: { top: 14, left: 14, borderTopWidth: 3, borderLeftWidth: 3 },
  qrCornerTopRight: { top: 14, right: 14, borderTopWidth: 3, borderRightWidth: 3 },
  qrCornerBottomLeft: { bottom: 14, left: 14, borderBottomWidth: 3, borderLeftWidth: 3 },
  qrCaption: { color: '#53657E', fontSize: 15, lineHeight: 22, fontWeight: '700', textAlign: 'center', marginTop: 18, paddingHorizontal: 16 },
  codeWrap: { alignItems: 'center', paddingTop: 18 },
  codeLabel: { color: '#07111F', fontSize: 17, fontWeight: '900', marginBottom: 16 },
  codeBoxes: { flexDirection: 'row', gap: 9 },
  codeBox: { width: 50, height: 58, borderRadius: 15, borderWidth: 1.5, borderColor: '#D8E1EC', backgroundColor: '#F8FAFC', alignItems: 'center', justifyContent: 'center' },
  codeChar: { color: '#07111F', fontSize: 24, fontWeight: '900' },
  allowedBox: { minHeight: 58, borderRadius: 16, backgroundColor: '#F0FDF4', borderWidth: 1, borderColor: '#BBF7D0', flexDirection: 'row', alignItems: 'center', gap: 10, paddingHorizontal: 16, marginTop: 20 },
  allowedText: { flex: 1, color: '#15803D', fontSize: 14, fontWeight: '800', lineHeight: 20 },
  shareInviteBtn: { minHeight: 58, borderRadius: 17, backgroundColor: '#0B8FF0', flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 9, marginTop: 16 },
  shareInviteText: { color: '#FFFFFF', fontSize: 17, fontWeight: '900' },
  historyList: { borderRadius: 17, backgroundColor: '#F8FAFC', overflow: 'hidden' },
  historyRow: { minHeight: 84, flexDirection: 'row', alignItems: 'center', gap: 14, paddingHorizontal: 16, borderBottomWidth: 1, borderBottomColor: '#E8EEF6' },
  historyIcon: { width: 44, height: 44, borderRadius: 22, backgroundColor: '#EAF4FF', alignItems: 'center', justifyContent: 'center' },
  historyTitle: { color: '#07111F', fontSize: 16, fontWeight: '900' },
  historySub: { color: '#53657E', fontSize: 13, fontWeight: '700', marginTop: 4 },
  historyTime: { color: '#94A3B8', fontSize: 12, fontWeight: '800', maxWidth: 78, textAlign: 'right' },
});

const emergencyStyles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: '#F5F7FB' },
  hero: { minHeight: 142, backgroundColor: '#18345A', flexDirection: 'row', alignItems: 'center', paddingHorizontal: 36, paddingTop: 34, gap: 16 },
  backBtn: { width: 46, height: 46, borderRadius: 23, backgroundColor: '#FFFFFF20', alignItems: 'center', justifyContent: 'center' },
  heroCopy: { flex: 1 },
  eyebrow: { color: '#9FB5D1', fontSize: 12, fontWeight: '900', letterSpacing: 1.8 },
  title: { color: '#FFFFFF', fontSize: 20, fontWeight: '900', marginTop: 4 },
  addTopBtn: { height: 42, borderRadius: 22, borderWidth: 1, borderColor: '#38BDF8', backgroundColor: '#0B5B9D', flexDirection: 'row', alignItems: 'center', justifyContent: 'center', paddingHorizontal: 16, gap: 6 },
  addTopText: { color: '#FFFFFF', fontSize: 15, fontWeight: '900' },
  scroll: { flex: 1 },
  content: { paddingHorizontal: 26, paddingTop: 20, paddingBottom: 112 },
  notice: { minHeight: 76, borderRadius: 17, borderWidth: 1, borderColor: '#FED7AA', backgroundColor: '#FFF7ED', flexDirection: 'row', alignItems: 'center', gap: 14, paddingHorizontal: 22, marginBottom: 18 },
  noticeText: { flex: 1, color: '#9A3412', fontSize: 15, lineHeight: 22, fontWeight: '700' },
  noticeBold: { fontWeight: '900' },
  contactCard: { minHeight: 114, borderRadius: 18, backgroundColor: '#FFFFFF', paddingHorizontal: 20, paddingVertical: 18, shadowColor: '#0F172A', shadowOpacity: 0.06, shadowOffset: { width: 0, height: 8 }, shadowRadius: 18, elevation: 2 },
  contactCardEditing: { paddingBottom: 18 },
  contactTopRow: { flexDirection: 'row', alignItems: 'center' },
  rankCircle: { width: 34, height: 34, borderRadius: 17, alignItems: 'center', justifyContent: 'center', marginRight: 14 },
  rankText: { color: '#FFFFFF', fontSize: 15, fontWeight: '900' },
  contactAvatar: { width: 50, height: 50, borderRadius: 25, backgroundColor: '#F1F5F9', alignItems: 'center', justifyContent: 'center', marginRight: 14 },
  contactEmoji: { fontSize: 24 },
  contactCopy: { flex: 1 },
  nameRow: { flexDirection: 'row', alignItems: 'center', gap: 8, flexWrap: 'wrap' },
  contactName: { color: '#07111F', fontSize: 18, fontWeight: '900' },
  lockedPill: { color: '#2563EB', fontSize: 11, fontWeight: '900', backgroundColor: '#EFF6FF', paddingHorizontal: 7, paddingVertical: 4, borderRadius: 8, overflow: 'hidden' },
  contactRole: { color: '#53657E', fontSize: 14, fontWeight: '700', marginTop: 4 },
  contactPhone: { color: '#07111F', fontSize: 14, fontWeight: '900', marginTop: 3 },
  contactActions: { alignItems: 'center', gap: 10 },
  callBtn: { width: 38, height: 38, borderRadius: 19, backgroundColor: '#DCFCE7', alignItems: 'center', justifyContent: 'center' },
  smallActions: { flexDirection: 'row', gap: 10 },
  editBtn: { width: 38, height: 38, borderRadius: 19, backgroundColor: '#EAF4FF', alignItems: 'center', justifyContent: 'center' },
  deleteBtn: { width: 38, height: 38, borderRadius: 19, backgroundColor: '#FEE2E2', alignItems: 'center', justifyContent: 'center' },
  editForm: { borderTopWidth: 1, borderTopColor: '#E2E8F0', marginTop: 18, paddingTop: 14, gap: 10 },
  editInput: { minHeight: 46, borderRadius: 16, borderWidth: 1, borderColor: '#D8E1EC', backgroundColor: '#F8FAFC', color: '#07111F', fontSize: 16, fontWeight: '700', paddingHorizontal: 16 },
  editButtons: { flexDirection: 'row', gap: 10, marginTop: 4 },
  saveBtn: { flex: 1, height: 46, borderRadius: 17, backgroundColor: '#0B8FF0', alignItems: 'center', justifyContent: 'center' },
  saveText: { color: '#FFFFFF', fontSize: 15, fontWeight: '900' },
  cancelEditBtn: { flex: 1, height: 46, borderRadius: 17, backgroundColor: '#EEF2F7', alignItems: 'center', justifyContent: 'center' },
  cancelEditText: { color: '#64748B', fontSize: 15, fontWeight: '900' },
  chainWrap: { alignItems: 'center', height: 34, justifyContent: 'center' },
  chainLine: { width: 2, height: 18 },
  addCard: { minHeight: 164, borderRadius: 18, borderWidth: 1.5, borderStyle: 'dashed', borderColor: '#B7D7FA', backgroundColor: '#EFF6FF', alignItems: 'center', justifyContent: 'center', marginTop: 18 },
  addCardTitle: { color: '#0B84FF', fontSize: 18, fontWeight: '900', marginTop: 14 },
  addCardSub: { color: '#94A3B8', fontSize: 14, fontWeight: '800', marginTop: 8 },
});

const historyStyles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: '#F3F7FB' },
  header: { minHeight: 134, backgroundColor: '#FFFFFF', borderBottomWidth: 1, borderBottomColor: '#E2E8F0', flexDirection: 'row', alignItems: 'center', paddingHorizontal: 18, paddingTop: 30, gap: 12 },
  backBtn: { width: 44, height: 44, borderRadius: 22, backgroundColor: '#F1F5F9', alignItems: 'center', justifyContent: 'center' },
  headerTitle: { flex: 1, color: '#07111F', fontSize: 21, fontWeight: '900' },
  personPill: { minHeight: 34, borderRadius: 17, backgroundColor: '#F1F5F9', paddingHorizontal: 12, alignItems: 'center', justifyContent: 'center' },
  personPillText: { color: '#2563EB', fontSize: 13, fontWeight: '900' },
  downloadBtn: { width: 42, height: 42, borderRadius: 21, backgroundColor: '#F1F5F9', alignItems: 'center', justifyContent: 'center' },
  tabBar: { backgroundColor: '#FFFFFF', borderBottomWidth: 1, borderBottomColor: '#E2E8F0' },
  tabContent: { gap: 10, paddingHorizontal: 18, paddingVertical: 14 },
  tabPill: { minHeight: 34, borderRadius: 18, backgroundColor: '#EEF2F7', flexDirection: 'row', alignItems: 'center', gap: 7, paddingHorizontal: 16 },
  tabPillActive: { backgroundColor: '#0B8FF0', shadowColor: '#0B8FF0', shadowOpacity: 0.25, shadowOffset: { width: 0, height: 6 }, shadowRadius: 10, elevation: 3 },
  tabText: { color: '#64748B', fontSize: 14, fontWeight: '900' },
  tabTextActive: { color: '#FFFFFF' },
  scroll: { flex: 1 },
  content: { paddingHorizontal: 18, paddingTop: 18, paddingBottom: 116 },
  rangeRow: { flexDirection: 'row', gap: 12, marginBottom: 16 },
  rangePill: { minHeight: 38, borderRadius: 20, backgroundColor: '#EEF2F7', alignItems: 'center', justifyContent: 'center', paddingHorizontal: 18 },
  rangePillActive: { backgroundColor: '#0B8FF0' },
  rangeText: { color: '#64748B', fontSize: 14, fontWeight: '900' },
  rangeTextActive: { color: '#FFFFFF' },
  summaryCard: { minHeight: 76, borderRadius: 18, borderWidth: 1, borderColor: '#BFDBFE', backgroundColor: '#EFF6FF', flexDirection: 'row', alignItems: 'center', marginBottom: 22 },
  statBlock: { flex: 1, alignItems: 'center', borderRightWidth: 1, borderRightColor: '#D6E4F2' },
  statLabel: { color: '#64748B', fontSize: 14, fontWeight: '700' },
  statValue: { color: '#07111F', fontSize: 17, fontWeight: '900', marginTop: 6 },
  blueText: { color: '#0B8FF0' },
  greenText: { color: '#22C55E' },
  sectionLabel: { color: '#607084', fontSize: 14, fontWeight: '900', letterSpacing: 1.2, marginBottom: 12 },
  timeline: { borderLeftWidth: 1, borderLeftColor: '#DCE5EF', marginLeft: 18, paddingLeft: 20 },
  timelineRow: { flexDirection: 'row', alignItems: 'center', marginBottom: 14 },
  timelineDot: { width: 22, height: 22, borderRadius: 11, borderWidth: 5, backgroundColor: '#FFFFFF', marginLeft: -32, marginRight: 14 },
  timelineCard: { flex: 1, minHeight: 82, borderRadius: 16, backgroundColor: '#FFFFFF', padding: 16, shadowColor: '#0F172A', shadowOpacity: 0.05, shadowOffset: { width: 0, height: 6 }, shadowRadius: 14, elevation: 2 },
  historyTitleRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12 },
  timelineTitle: { color: '#111827', fontSize: 18, fontWeight: '900' },
  timelineMeta: { color: '#8A9AB4', fontSize: 14, fontWeight: '700', marginTop: 12 },
  greenPill: { color: '#16A34A', fontSize: 12, fontWeight: '900', backgroundColor: '#DCFCE7', paddingHorizontal: 11, paddingVertical: 6, borderRadius: 13, overflow: 'hidden' },
  durationPill: { minHeight: 38, borderRadius: 19, borderWidth: 1, borderStyle: 'dashed', borderColor: '#93C5FD', backgroundColor: '#EAF4FF', justifyContent: 'center', paddingHorizontal: 18, marginLeft: 0, marginBottom: 14 },
  durationText: { color: '#2563EB', fontSize: 14, fontWeight: '900' },
  listBlock: { gap: 16 },
  routeCard: { borderRadius: 17, backgroundColor: '#FFFFFF', padding: 18, shadowColor: '#0F172A', shadowOpacity: 0.06, shadowOffset: { width: 0, height: 8 }, shadowRadius: 18, elevation: 2 },
  routeCardExpanded: { paddingBottom: 20 },
  routeMainRow: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  routeIconBox: { width: 78, height: 68, borderRadius: 12, backgroundColor: '#EAF4FF', alignItems: 'center', justifyContent: 'center' },
  routeDay: { color: '#94A3B8', fontSize: 12, fontWeight: '900', marginBottom: 6 },
  routeTitle: { color: '#07111F', fontSize: 18, fontWeight: '900' },
  routeMeta: { color: '#52647C', fontSize: 15, fontWeight: '700', marginTop: 6 },
  statusPill: { fontSize: 13, fontWeight: '900', paddingHorizontal: 12, paddingVertical: 7, borderRadius: 14, overflow: 'hidden' },
  routeExpanded: { borderTopWidth: 1, borderTopColor: '#EEF2F7', marginTop: 18, paddingTop: 16 },
  miniRouteMap: { height: 104, borderRadius: 16, borderWidth: 1, borderColor: '#93C5FD', backgroundColor: '#EAF7FF', overflow: 'hidden', marginBottom: 14 },
  mapPointA: { position: 'absolute', left: 58, top: 45, width: 15, height: 15, borderRadius: 8, backgroundColor: '#0B8FF0' },
  mapPointMid: { position: 'absolute', left: '52%', top: 38, width: 14, height: 14, borderRadius: 7, backgroundColor: '#F59E0B' },
  mapPointB: { position: 'absolute', right: 46, top: 43, width: 15, height: 15, borderRadius: 8, backgroundColor: '#22C55E' },
  routeDashOne: { position: 'absolute', left: 70, top: 52, width: 130, height: 4, borderRadius: 2, backgroundColor: '#0EA5E9', transform: [{ rotate: '4deg' }] },
  routeDashTwo: { position: 'absolute', right: 58, top: 49, width: 124, height: 4, borderRadius: 2, backgroundColor: '#22C55E', transform: [{ rotate: '-10deg' }] },
  mapLabelA: { position: 'absolute', left: 58, bottom: 18, color: '#0B8FF0', fontSize: 12, fontWeight: '900' },
  mapLabelB: { position: 'absolute', right: 47, bottom: 18, color: '#16A34A', fontSize: 12, fontWeight: '900' },
  warningMapIcon: { position: 'absolute', left: '53%', top: 18, color: '#F59E0B', fontSize: 16, fontWeight: '900' },
  routeSteps: { gap: 8 },
  stepRow: { flexDirection: 'row', alignItems: 'center' },
  stepBubble: { width: 25, height: 25, borderRadius: 13, alignItems: 'center', justifyContent: 'center', marginRight: 10 },
  stepNumber: { color: '#FFFFFF', fontSize: 12, fontWeight: '900' },
  stepTitle: { color: '#111827', fontSize: 15, fontWeight: '900' },
  stepSub: { color: '#94A3B8', fontSize: 14, fontWeight: '800' },
  deviationNote: { borderRadius: 16, borderWidth: 1, borderColor: '#FCD34D', backgroundColor: '#FFFBEB', padding: 15, marginTop: 14 },
  deviationTitle: { color: '#D97706', fontSize: 15, fontWeight: '900' },
  deviationText: { color: '#92400E', fontSize: 14, fontWeight: '700', marginTop: 6 },
  sosCard: { borderRadius: 18, borderWidth: 1, borderColor: '#FECACA', backgroundColor: '#FFFFFF', overflow: 'hidden', shadowColor: '#0F172A', shadowOpacity: 0.06, shadowOffset: { width: 0, height: 8 }, shadowRadius: 18, elevation: 2 },
  sosHeader: { minHeight: 88, backgroundColor: '#FEF2F2', flexDirection: 'row', justifyContent: 'space-between', padding: 18 },
  sosEvent: { color: '#EF4444', fontSize: 13, fontWeight: '900', letterSpacing: 1.3 },
  sosTitle: { color: '#07111F', fontSize: 18, fontWeight: '900', marginTop: 8 },
  resolvedPill: { color: '#16A34A', fontSize: 14, fontWeight: '900', backgroundColor: '#DCFCE7', paddingHorizontal: 12, paddingVertical: 6, borderRadius: 14, overflow: 'hidden' },
  sosDuration: { color: '#52647C', fontSize: 12, fontWeight: '700', marginTop: 8 },
  sosBody: { padding: 18 },
  sosLine: { flexDirection: 'row', alignItems: 'center', gap: 14, marginBottom: 14 },
  sosTime: { color: '#94A3B8', fontSize: 14, fontWeight: '900', width: 72 },
  sosText: { flex: 1, color: '#07111F', fontSize: 15, fontWeight: '900' },
  sosDetails: { borderRadius: 16, borderWidth: 1, borderColor: '#DCE5EF', backgroundColor: '#F8FAFC', padding: 14, marginTop: 8 },
  detailRow: { flexDirection: 'row', justifyContent: 'space-between', gap: 14, marginBottom: 9 },
  detailLabel: { color: '#52647C', fontSize: 14, fontWeight: '700' },
  detailValue: { flex: 1, color: '#07111F', fontSize: 14, fontWeight: '900', textAlign: 'right' },
  walkCard: { borderRadius: 17, backgroundColor: '#FFFFFF', padding: 20, shadowColor: '#0F172A', shadowOpacity: 0.06, shadowOffset: { width: 0, height: 8 }, shadowRadius: 18, elevation: 2 },
  walkCardExpanded: { borderWidth: 1, borderColor: '#BFDBFE' },
  walkDetails: { borderTopWidth: 1, borderTopColor: '#EEF2F7', marginTop: 16, paddingTop: 14 },
  alertDuring: { color: '#D97706', fontSize: 13, fontWeight: '900', marginTop: 10 },
  eventList: { gap: 14 },
  filterRow: { flexDirection: 'row', gap: 10, marginBottom: 6 },
  filterPill: { minHeight: 36, borderRadius: 18, backgroundColor: '#EEF2F7', alignItems: 'center', justifyContent: 'center', paddingHorizontal: 18 },
  filterPillActive: { backgroundColor: '#0B8FF0' },
  filterEmergency: { backgroundColor: '#EF4444' },
  filterWarning: { backgroundColor: '#F59E0B' },
  filterText: { color: '#64748B', fontSize: 14, fontWeight: '900' },
  filterTextActive: { color: '#FFFFFF' },
  eventRow: { flexDirection: 'row', alignItems: 'center', gap: 14 },
  sideDot: { width: 20, height: 20, borderRadius: 10, borderWidth: 6, backgroundColor: '#FFFFFF' },
  eventCard: { flex: 1, minHeight: 74, borderRadius: 17, backgroundColor: '#FFFFFF', padding: 16, shadowColor: '#0F172A', shadowOpacity: 0.06, shadowOffset: { width: 0, height: 8 }, shadowRadius: 18, elevation: 2 },
  eventTitleWrap: { flex: 1, flexDirection: 'row', alignItems: 'center', gap: 12 },
  eventTitle: { flex: 1, color: '#07111F', fontSize: 18, fontWeight: '900' },
  responseText: { color: '#16A34A', fontSize: 14, fontWeight: '900', marginTop: 12 },
  historyNotice: { minHeight: 72, borderRadius: 16, borderWidth: 1, borderColor: '#93C5FD', backgroundColor: '#EAF4FF', flexDirection: 'row', alignItems: 'center', gap: 14, paddingHorizontal: 20, marginTop: 12 },
  historyNoticeTitle: { color: '#07111F', fontSize: 14, fontWeight: '900' },
  historyNoticeSub: { color: '#52647C', fontSize: 13, fontWeight: '700', marginTop: 4 },
});

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: '#F5F7FB' },
  scroll: { flex: 1 },
  content: { paddingBottom: 112 },
  hero: { backgroundColor: '#132843', paddingHorizontal: 28, paddingTop: 40, paddingBottom: 26 },
  heroRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  brandRow: { flexDirection: 'row', alignItems: 'center' },
  logoCircle: { width: 43, height: 43, borderRadius: 16, alignItems: 'center', justifyContent: 'center', marginRight: 12, backgroundColor: 'rgba(12,198,214,0.12)' },
  avatarCircle: { width: 70, height: 70, borderRadius: 35, borderWidth: 2, borderColor: '#0B84FF', alignItems: 'center', justifyContent: 'center', marginRight: 16, backgroundColor: 'rgba(14,165,233,0.15)' },
  avatarEmoji: { fontSize: 30 },
  personName: { color: '#FFFFFF', fontSize: 20, fontWeight: '900' },
  personMeta: { color: '#9FB5D1', fontSize: 14, fontWeight: '700', marginTop: 4 },
  planCard: { marginHorizontal: 26, marginTop: 20, borderRadius: 18, padding: 20, overflow: 'hidden' },
  planLabel: { color: 'rgba(255,255,255,0.72)', fontSize: 11, fontWeight: '900', letterSpacing: 1.2 },
  planName: { color: '#FFFFFF', fontSize: 20, fontWeight: '900', marginTop: 8 },
  planMeta: { color: 'rgba(255,255,255,0.86)', fontSize: 13, fontWeight: '700', marginTop: 6 },
  priceWrap: { position: 'absolute', top: 22, right: 20, alignItems: 'flex-end' },
  price: { color: '#FFFFFF', fontSize: 30, fontWeight: '900' },
  perMonth: { color: 'rgba(255,255,255,0.75)', fontSize: 11, fontWeight: '700' },
  planButtons: { flexDirection: 'row', gap: 10, marginTop: 18 },
  manageBtn: { flex: 1, height: 44, borderRadius: 22, alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(255,255,255,0.20)', borderWidth: 1, borderColor: 'rgba(255,255,255,0.22)' },
  manageText: { color: '#FFFFFF', fontSize: 14, fontWeight: '900' },
  addBtn: { flex: 1, height: 44, borderRadius: 22, alignItems: 'center', justifyContent: 'center', backgroundColor: '#FFFFFF' },
  addText: { color: '#0EA5E9', fontSize: 13, fontWeight: '900' },
  section: { paddingHorizontal: 26, marginTop: 20 },
  sectionTitle: { color: '#60799D', fontSize: 14, fontWeight: '900', letterSpacing: 1.3, marginBottom: 12 },
  card: { borderRadius: 16, backgroundColor: '#FFFFFF', overflow: 'hidden', shadowColor: '#0F172A', shadowOpacity: 0.06, shadowOffset: { width: 0, height: 8 }, shadowRadius: 18, elevation: 2 },
  row: { minHeight: 84, flexDirection: 'row', alignItems: 'center', paddingHorizontal: 20 },
  rowBorder: { borderTopWidth: 1, borderTopColor: '#EEF2F7' },
  rowIcon: { width: 44, height: 44, borderRadius: 22, alignItems: 'center', justifyContent: 'center', marginRight: 16 },
  rowCopy: { flex: 1 },
  rowTitle: { color: '#07111F', fontSize: 17, fontWeight: '900' },
  rowSub: { color: '#425C7A', fontSize: 14, fontWeight: '600', marginTop: 4 },
  signOutBtn: { marginHorizontal: 26, marginTop: 22, minHeight: 60, borderRadius: 16, borderWidth: 1, borderColor: '#FECACA', backgroundColor: '#FFF1F2', flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 10 },
  signOutText: { color: '#EF4444', fontSize: 17, fontWeight: '900' },
  versionText: { color: '#94A3B8', fontSize: 12, fontWeight: '700', textAlign: 'center', marginTop: 24 },
});
