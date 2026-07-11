// DPDP-MOB-01 — Mobile Privacy Screen.
// Mirrors the web `/m/privacy` page on Expo React Native.
//
// Data-principal-rights surface required by DPDP §11:
//   • Right of access     — render the JSON payload below
//   • Right to portability — JSON + PDF downloads via Share Sheet
//   • Right to nominate    — listed in the rights footer
//   • Right to erasure     — self-serve via DELETE /api/privacy/me (NISCH-009)
//   • Right to grievance   — privacy@nischint.care mailto
//
// Strict TypeScript. Zero `any` in the public surface.
import React, { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator, Alert, Linking, ScrollView, StyleSheet,
  Text, TouchableOpacity, View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import * as FileSystem from 'expo-file-system/legacy';
import * as Sharing from 'expo-sharing';
import { useRouter } from 'expo-router';
import { useAuthStore } from '@/stores/authStore';
import { colors } from '@/theme';
import api from '@/services/api';
import { setConsentDecision, type ConsentCategory } from '@/services/consentService';

// ── Types ────────────────────────────────────────────────────────────
interface Processor {
  name: string;
  purpose: string;
  data_categories: string[];
  data_residency: string;
}
interface Disclosures {
  audio: string;
  video: string;
  biometrics: string;
  retention_days: Record<string, number>;
}
interface ConsentRow {
  category: ConsentCategory;
  label_en: string;
  label_hi: string;
  purpose_en: string;
  purpose_hi: string;
  required_for: string;
  granted: boolean;
  granted_at: string | null;
  revoked_at: string | null;
}

interface PrivacyExport {
  data_principal: {
    user_id: string;
    name: string | null;
    email: string;
    phone: string | null;
    role: string;
    created_at: string;
  };
  seniors_under_care: { id: string; name: string }[];
  data_categories: string[];
  third_party_processors: Processor[];
  privacy_disclosures: Disclosures;
  data_principal_rights: Record<string, string>;
  generated_at: string;
}

// ── Helpers ──────────────────────────────────────────────────────────
async function fetchJson(token: string): Promise<PrivacyExport> {
  const res = await api.get<PrivacyExport>('/privacy/me');
  return res.data;
}

async function downloadAndShare(
  filename: string,
  bytes: string,
  encoding: 'base64' | 'utf8',
  mimeType: string,
): Promise<void> {
  const cacheDir = FileSystem.cacheDirectory ?? FileSystem.documentDirectory ?? '';
  const uri = `${cacheDir}${filename}`;
  await FileSystem.writeAsStringAsync(uri, bytes, {
    encoding: encoding === 'base64' ? 'base64' : 'utf8',
  });
  const canShare = await Sharing.isAvailableAsync();
  if (canShare) {
    await Sharing.shareAsync(uri, { mimeType, UTI: mimeType === 'application/pdf' ? 'com.adobe.pdf' : 'public.json' });
  }
}

// ── Test seam — overridable so the test runner can isolate I/O ──────
type Deps = {
  fetchJson: typeof fetchJson;
  downloadAndShare: typeof downloadAndShare;
  fetchPdfBase64: (token: string) => Promise<string>;
};
let _depsOverride: Partial<Deps> | null = null;
export function __setPrivacyDeps(d: Partial<Deps> | null): void { _depsOverride = d; }

async function fetchPdfBase64(token: string): Promise<string> {
  const apiBase = (api.defaults.baseURL ?? '').replace(/\/$/, '');
  const res = await fetch(`${apiBase}/privacy/me?format=pdf`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(`pdf fetch failed status=${res.status}`);
  const buf = await res.arrayBuffer();
  let binary = '';
  const arr = new Uint8Array(buf);
  for (let i = 0; i < arr.byteLength; i += 1) binary += String.fromCharCode(arr[i]);
  const atobFn = (globalThis as { btoa?: (s: string) => string }).btoa;
  return atobFn ? atobFn(binary) : binary;
}

// ── Screen ───────────────────────────────────────────────────────────
export default function PrivacyScreen(): React.ReactElement {
  const router = useRouter();
  const { token } = useAuthStore();
  const [data, setData] = useState<PrivacyExport | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [downloadingJson, setDownloadingJson] = useState<boolean>(false);
  const [downloadingPdf, setDownloadingPdf] = useState<boolean>(false);
  const [consents, setConsents] = useState<ConsentRow[]>([]);
  const [updatingConsent, setUpdatingConsent] = useState<ConsentCategory | null>(null);

  // ── NISCH-009: self-serve erasure state ───────────────────────────
  const [erasureState, setErasureState] = useState<'idle' | 'pending' | 'loading' | 'cancelling'>('idle');
  const [erasureId, setErasureId] = useState<string | null>(null);
  const [erasureExpiry, setErasureExpiry] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const fn = _depsOverride?.fetchJson ?? fetchJson;
      const payload = await fn(token ?? '');
      setData(payload);
      try {
        const cres = await api.get<ConsentRow[]>('/privacy/consents/me');
        setConsents(cres.data ?? []);
      } catch {
        setConsents([]);
      }
    } catch (e) {
      setError((e instanceof Error ? e.message : 'Failed to load privacy data'));
    } finally {
      setLoading(false);
    }
  }, [token]);

  const onToggleConsent = useCallback(
    async (category: ConsentCategory, nextGranted: boolean) => {
      setUpdatingConsent(category);
      setConsents((prev) =>
        prev.map((c) => (c.category === category ? { ...c, granted: nextGranted } : c)),
      );
      try {
        await setConsentDecision(category, nextGranted);
      } catch {
        setConsents((prev) =>
          prev.map((c) => (c.category === category ? { ...c, granted: !nextGranted } : c)),
        );
      } finally {
        setUpdatingConsent(null);
      }
    },
    [],
  );

  useEffect(() => { void load(); }, [load]);

  const onDownloadJson = useCallback(async () => {
    if (!data) return;
    setDownloadingJson(true);
    try {
      const ds = _depsOverride?.downloadAndShare ?? downloadAndShare;
      await ds(
        `nischint-privacy-${data.data_principal.user_id}.json`,
        JSON.stringify(data, null, 2),
        'utf8',
        'application/json',
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : 'JSON download failed');
    } finally {
      setDownloadingJson(false);
    }
  }, [data]);

  const onDownloadPdf = useCallback(async () => {
    if (!token || !data) return;
    setDownloadingPdf(true);
    try {
      const pdfFn = _depsOverride?.fetchPdfBase64 ?? fetchPdfBase64;
      const ds = _depsOverride?.downloadAndShare ?? downloadAndShare;
      const b64 = await pdfFn(token);
      await ds(
        `nischint-privacy-${data.data_principal.user_id}.pdf`,
        b64,
        'base64',
        'application/pdf',
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : 'PDF download failed');
    } finally {
      setDownloadingPdf(false);
    }
  }, [token, data]);

  // ── NISCH-009 handlers ────────────────────────────────────────────
  async function submitErasure() {
    Alert.alert(
      'Delete your account?',
      'Your data will be permanently deleted after a 30-day grace period. You can cancel anytime before then.',
      [
        { text: 'Keep account', style: 'cancel' },
        {
          text: 'Request deletion',
          style: 'destructive',
          onPress: async () => {
            setErasureState('loading');
            try {
              const res = await api.delete<{
                erasure_request_id: string;
                grace_expires_at: string;
              }>('/privacy/me');
              setErasureId(res.data.erasure_request_id);
              setErasureExpiry(res.data.grace_expires_at);
              setErasureState('pending');
            } catch (e) {
              setErasureState('idle');
              Alert.alert('Error', 'Could not submit erasure request. Please try again.');
            }
          },
        },
      ],
    );
  }

  async function cancelErasure() {
    if (!erasureId) return;
    setErasureState('cancelling');
    try {
      await api.post(`/privacy/erasure-requests/${erasureId}/cancel`);
      setErasureId(null);
      setErasureExpiry(null);
      setErasureState('idle');
      Alert.alert('Cancelled', 'Your account deletion request has been cancelled.');
    } catch (e) {
      setErasureState('pending');
      Alert.alert('Error', 'Could not cancel. Please try again or contact privacy@nischint.care');
    }
  }

  // ── Loading skeleton ───────────────────────────────────────────────
  if (loading) {
    return (
      <SafeAreaView style={styles.container} testID="privacy-screen-loading">
        <View style={styles.header}>
          <TouchableOpacity onPress={() => router.back()} testID="privacy-back-btn">
            <Text style={styles.headerBack}>←</Text>
          </TouchableOpacity>
          <Text style={styles.headerTitle}>Privacy & My Data</Text>
        </View>
        <View style={styles.center}>
          <ActivityIndicator size="large" color={colors.primary} />
          <Text style={styles.muted}>Loading your privacy export…</Text>
        </View>
      </SafeAreaView>
    );
  }

  // ── Error state ────────────────────────────────────────────────────
  if (error || !data) {
    return (
      <SafeAreaView style={styles.container} testID="privacy-screen-error">
        <View style={styles.header}>
          <TouchableOpacity onPress={() => router.back()} testID="privacy-back-btn">
            <Text style={styles.headerBack}>←</Text>
          </TouchableOpacity>
          <Text style={styles.headerTitle}>Privacy & My Data</Text>
        </View>
        <View style={styles.center}>
          <Text style={styles.errorText}>{error ?? 'Could not load privacy data.'}</Text>
          <TouchableOpacity style={styles.btn} onPress={load} testID="privacy-retry-btn">
            <Text style={styles.btnText}>Retry</Text>
          </TouchableOpacity>
        </View>
      </SafeAreaView>
    );
  }

  // ── Loaded ─────────────────────────────────────────────────────────
  return (
    <SafeAreaView style={styles.container} testID="privacy-screen">
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} testID="privacy-back-btn">
          <Text style={styles.headerBack}>←</Text>
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Privacy & My Data</Text>
      </View>

      <ScrollView contentContainerStyle={styles.scrollBody}>
        {/* Residency badge */}
        <View style={styles.residencyRow} testID="privacy-residency-badge">
          <Text style={styles.residencyFlag}>🇮🇳</Text>
          <Text style={styles.residencyText}>
            Stored in AWS Mumbai (ap-south-1) under Indian jurisdiction
          </Text>
        </View>

        {/* Data principal */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>You (Data Principal)</Text>
          <Text style={styles.label}>Name</Text>
          <Text style={styles.value} testID="privacy-principal-name">
            {data.data_principal.name ?? '—'}
          </Text>
          <Text style={styles.label}>Email</Text>
          <Text style={styles.value}>{data.data_principal.email}</Text>
          <Text style={styles.label}>Role</Text>
          <Text style={styles.value}>{data.data_principal.role}</Text>
          <Text style={styles.label}>Seniors under your care</Text>
          <Text style={styles.value} testID="privacy-seniors-count">
            {data.seniors_under_care.length}
          </Text>
        </View>

        {/* Data categories */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Data we process about you</Text>
          {data.data_categories.map((c) => (
            <Text key={c} style={styles.bullet}>• {c}</Text>
          ))}
        </View>

        {/* Audio / video / biometrics disclosures */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>What we do NOT store</Text>
          <Text style={styles.disclosureLabel}>Audio</Text>
          <Text style={styles.disclosure} testID="privacy-audio-disclosure">
            {data.privacy_disclosures.audio}
          </Text>
          <Text style={styles.disclosureLabel}>Video</Text>
          <Text style={styles.disclosure}>{data.privacy_disclosures.video}</Text>
          <Text style={styles.disclosureLabel}>Biometrics</Text>
          <Text style={styles.disclosure}>{data.privacy_disclosures.biometrics}</Text>
        </View>

        {/* Retention */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Retention periods</Text>
          {Object.entries(data.privacy_disclosures.retention_days).map(([k, v]) => (
            <View key={k} style={styles.kvRow}>
              <Text style={styles.kvKey}>{k.replace(/_/g, ' ')}</Text>
              <Text style={styles.kvValue} testID={`privacy-retention-${k}`}>{v} days</Text>
            </View>
          ))}
        </View>

        {/* Third-party processors */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Third-party processors</Text>
          {data.third_party_processors.map((p) => (
            <View key={p.name} style={styles.processorCard} testID={`privacy-processor-${p.name}`}>
              <Text style={styles.processorName}>{p.name}</Text>
              <Text style={styles.processorPurpose}>{p.purpose}</Text>
              <Text style={styles.processorMeta}>Categories: {p.data_categories.join(', ')}</Text>
              <Text style={styles.processorMeta}>Residency: {p.data_residency}</Text>
            </View>
          ))}
        </View>

        {/* Consent toggles */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Consent settings</Text>
          <Text style={styles.bodyText}>
            Toggle a category off and Nischint stops asking your phone
            for that permission. Toggle back on and you&apos;ll be
            re-prompted next time the feature needs it.
          </Text>
          {consents.length === 0 ? (
            <Text style={styles.metaText} testID="consent-rows-empty">
              No consent decisions on file yet.
            </Text>
          ) : (
            consents.map((c) => {
              const isUpdating = updatingConsent === c.category;
              return (
                <View
                  key={c.category}
                  style={styles.consentRow}
                  testID={`consent-row-${c.category}`}
                >
                  <View style={styles.consentRowText}>
                    <Text style={styles.consentRowLabel}>{c.label_en}</Text>
                    <Text style={styles.consentRowPurpose} numberOfLines={2}>
                      {c.purpose_en}
                    </Text>
                  </View>
                  <TouchableOpacity
                    style={[
                      styles.consentToggle,
                      c.granted ? styles.consentToggleOn : styles.consentToggleOff,
                      isUpdating && styles.btnDisabled,
                    ]}
                    disabled={isUpdating}
                    onPress={() => onToggleConsent(c.category, !c.granted)}
                    testID={`consent-toggle-${c.category}`}
                  >
                    <Text
                      style={[
                        styles.consentToggleText,
                        c.granted ? styles.consentToggleTextOn : styles.consentToggleTextOff,
                      ]}
                    >
                      {isUpdating ? '…' : c.granted ? 'On' : 'Off'}
                    </Text>
                  </TouchableOpacity>
                </View>
              );
            })
          )}
        </View>

        {/* Downloads */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Take your data with you</Text>
          <TouchableOpacity
            style={[styles.btn, downloadingPdf && styles.btnDisabled]}
            disabled={downloadingPdf}
            onPress={onDownloadPdf}
            testID="privacy-download-pdf-btn"
          >
            <Text style={styles.btnText}>
              {downloadingPdf ? 'Preparing PDF…' : 'Download my data (PDF)'}
            </Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.btnSecondary, downloadingJson && styles.btnDisabled]}
            disabled={downloadingJson}
            onPress={onDownloadJson}
            testID="privacy-download-json-btn"
          >
            <Text style={styles.btnSecondaryText}>
              {downloadingJson ? 'Preparing JSON…' : 'Download as JSON'}
            </Text>
          </TouchableOpacity>
        </View>

        {/* NISCH-009: Self-serve account erasure */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Right to erasure (DPDP §17)</Text>
          <Text style={styles.bodyText}>
            Request permanent deletion of your account and all associated data.
            A 30-day grace period applies — you can cancel anytime before then.
          </Text>

          {erasureState === 'idle' && (
            <TouchableOpacity
              style={styles.btnDestructive}
              onPress={submitErasure}
              testID="privacy-erasure-btn"
            >
              <Text style={styles.btnDestructiveText}>Request account deletion</Text>
            </TouchableOpacity>
          )}

          {erasureState === 'loading' && (
            <ActivityIndicator
              color="#dc2626"
              style={{ marginTop: 12 }}
              testID="privacy-erasure-loading"
            />
          )}

          {(erasureState === 'pending' || erasureState === 'cancelling') && (
            <View style={styles.erasurePendingBox} testID="privacy-erasure-pending">
              <View style={{ flex: 1 }}>
                <Text style={styles.erasurePendingTitle}>⚠ Deletion scheduled</Text>
                {erasureExpiry && (
                  <Text style={styles.erasurePendingSubtitle}>
                    Data will be deleted on {new Date(erasureExpiry).toLocaleDateString()}
                  </Text>
                )}
              </View>
              <TouchableOpacity
                onPress={cancelErasure}
                disabled={erasureState === 'cancelling'}
                testID="privacy-erasure-cancel-btn"
              >
                <Text style={styles.cancelErasureText}>
                  {erasureState === 'cancelling' ? 'Cancelling…' : 'Cancel'}
                </Text>
              </TouchableOpacity>
            </View>
          )}
        </View>

        {/* DPO Contact */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Data Protection Officer</Text>
          <Text style={styles.bodyText}>
            Nischint has a designated DPO under the Digital Personal Data
            Protection Act, 2023 (§10). Reach them directly for any data
            grievance, access request, or escalation.
          </Text>
          <TouchableOpacity
            style={styles.linkRow}
            onPress={() => Linking.openURL('mailto:privacy@nischint.care?subject=DPDP%20enquiry')}
            testID="privacy-dpo-email"
          >
            <Text style={styles.linkText}>privacy@nischint.care</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={styles.linkRow}
            onPress={() => {
              const url = `${process.env.EXPO_PUBLIC_API_URL || 'https://nischint.care'}/api/dpo`;
              Linking.openURL(url);
            }}
            testID="privacy-dpo-page-link"
          >
            <Text style={styles.linkText}>View full DPO statement →</Text>
          </TouchableOpacity>
          <Text style={styles.metaText}>
            Initial acknowledgement within 7 days · Substantive response within 30 days.
          </Text>
        </View>

        {/* Grievance */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Questions about your data?</Text>
          <TouchableOpacity
            onPress={() => Linking.openURL('mailto:privacy@nischint.care')}
            testID="privacy-grievance-link"
          >
            <Text style={styles.linkText}>privacy@nischint.care</Text>
          </TouchableOpacity>
        </View>

        <Text style={styles.footer}>
          Generated {new Date(data.generated_at).toLocaleString()}
        </Text>
      </ScrollView>
    </SafeAreaView>
  );
}

// ── Styles ───────────────────────────────────────────────────────────
const styles = StyleSheet.create({
  container:   { flex: 1, backgroundColor: '#f7f8fa' },
  header:      { flexDirection: 'row', alignItems: 'center', padding: 16,
                 borderBottomWidth: 1, borderBottomColor: '#e4e7eb',
                 backgroundColor: '#fff' },
  headerBack:  { fontSize: 28, color: colors.primary, marginRight: 12 },
  headerTitle: { fontSize: 18, fontWeight: '700', color: '#1a1f2e' },
  scrollBody:  { padding: 16, paddingBottom: 64 },
  center:      { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 32 },
  muted:       { color: '#6b7280', marginTop: 12 },
  errorText:   { color: '#b91c1c', marginBottom: 16, textAlign: 'center' },

  residencyRow: { flexDirection: 'row', alignItems: 'center',
                  backgroundColor: '#ecfdf5', borderColor: '#10b981',
                  borderWidth: 1, borderRadius: 8, padding: 12, marginBottom: 16 },
  residencyFlag: { fontSize: 22, marginRight: 10 },
  residencyText: { color: '#065f46', flex: 1 },

  section:      { backgroundColor: '#fff', padding: 16, borderRadius: 12,
                  marginBottom: 12, borderWidth: 1, borderColor: '#eef0f3' },
  sectionTitle: { fontSize: 16, fontWeight: '700', color: '#1a1f2e', marginBottom: 12 },
  label:        { fontSize: 12, color: '#6b7280', marginTop: 6 },
  value:        { fontSize: 15, color: '#1a1f2e', fontWeight: '500' },
  bullet:       { fontSize: 14, color: '#1a1f2e', marginVertical: 2 },

  disclosureLabel: { fontSize: 12, fontWeight: '700', color: '#374151', marginTop: 8 },
  disclosure:      { fontSize: 13, color: '#4b5563', lineHeight: 18, marginTop: 2 },

  kvRow:    { flexDirection: 'row', justifyContent: 'space-between',
              paddingVertical: 6, borderBottomColor: '#eef0f3', borderBottomWidth: 1 },
  kvKey:    { color: '#4b5563', textTransform: 'capitalize' },
  kvValue:  { color: '#1a1f2e', fontWeight: '600' },

  processorCard:    { backgroundColor: '#f9fafb', borderRadius: 8, padding: 10, marginBottom: 8 },
  processorName:    { fontWeight: '700', color: '#1a1f2e', marginBottom: 2 },
  processorPurpose: { color: '#374151', fontSize: 13, marginBottom: 4 },
  processorMeta:    { color: '#6b7280', fontSize: 12 },

  btn:           { backgroundColor: colors.primary, padding: 14,
                   borderRadius: 10, marginTop: 8, alignItems: 'center' },
  btnText:       { color: '#fff', fontWeight: '700' },
  btnSecondary:  { backgroundColor: '#fff', padding: 14, borderRadius: 10, marginTop: 8,
                   alignItems: 'center', borderWidth: 1, borderColor: colors.primary },
  btnSecondaryText: { color: colors.primary, fontWeight: '700' },
  btnDisabled:   { opacity: 0.5 },

  linkText:      { color: colors.primary, fontWeight: '600' },
  linkRow:       { paddingVertical: 6 },
  bodyText:      { color: '#374151', fontSize: 13, lineHeight: 19, marginBottom: 6 },
  metaText:      { color: '#9ca3af', fontSize: 11, marginTop: 6 },
  footer:        { color: '#9ca3af', fontSize: 11, textAlign: 'center', marginTop: 16 },

  consentRow:           { flexDirection: 'row', alignItems: 'center', paddingVertical: 10,
                          borderBottomColor: '#eef0f3', borderBottomWidth: 1 },
  consentRowText:       { flex: 1, paddingRight: 12 },
  consentRowLabel:      { fontSize: 14, fontWeight: '600', color: '#1a1f2e' },
  consentRowPurpose:    { fontSize: 11, color: '#6b7280', marginTop: 2, lineHeight: 15 },
  consentToggle:        { paddingHorizontal: 14, paddingVertical: 6, borderRadius: 14, minWidth: 56,
                          alignItems: 'center' },
  consentToggleOn:      { backgroundColor: colors.primary },
  consentToggleOff:     { backgroundColor: '#e5e7eb' },
  consentToggleText:    { fontWeight: '700', fontSize: 12 },
  consentToggleTextOn:  { color: '#fff' },
  consentToggleTextOff: { color: '#374151' },

  // NISCH-009 erasure styles
  btnDestructive:      { backgroundColor: '#fef2f2', borderWidth: 1, borderColor: '#dc2626',
                         borderRadius: 10, paddingVertical: 14, alignItems: 'center', marginTop: 8 },
  btnDestructiveText:  { color: '#dc2626', fontWeight: '700', fontSize: 14 },
  erasurePendingBox:   { flexDirection: 'row', alignItems: 'center', gap: 10,
                         backgroundColor: '#fef2f2', borderWidth: 1, borderColor: '#dc2626',
                         borderRadius: 10, padding: 12, marginTop: 8 },
  erasurePendingTitle: { color: '#b91c1c', fontWeight: '700', fontSize: 13 },
  erasurePendingSubtitle: { color: '#dc2626', fontSize: 11, marginTop: 2 },
  cancelErasureText:   { color: '#2563eb', fontWeight: '700', fontSize: 13 },
});
