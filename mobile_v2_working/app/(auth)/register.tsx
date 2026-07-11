import { useMemo, useRef, useState } from 'react';
import {
  Alert,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { NischintLogo } from '@/components/NischintLogo';

export default function RegisterScreen() {
  const [phone, setPhone] = useState('');
  const [step, setStep] = useState<'phone' | 'otp'>('phone');
  const [otp, setOtp] = useState('');
  const router = useRouter();
  const inputRef = useRef<TextInput>(null);
  const otpRef = useRef<TextInput>(null);
  const digits = useMemo(() => phone.replace(/\D/g, '').slice(0, 10), [phone]);
  const canContinue = digits.length >= 10;

  const safeBack = () => {
    if (router.canGoBack()) {
      router.back();
      return;
    }
    router.replace('/intro');
  };

  const handleContinue = () => {
    if (!canContinue) {
      Alert.alert('Phone number required', 'Please enter a valid 10 digit mobile number.');
      return;
    }
    setStep('otp');
  };

  const handleVerify = () => {
    if (otp.length < 6) {
      Alert.alert('Verification code required', 'Please enter the 6 digit verification code.');
      return;
    }
    router.push({
      pathname: '/(auth)/profile-select',
      params: { phone: digits },
    });
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
          <Pressable accessibilityLabel="Back" onPress={() => (step === 'otp' ? setStep('phone') : safeBack())} style={styles.backButton}>
            <Ionicons name="chevron-back" size={24} color="#0F172A" />
          </Pressable>

          {step === 'phone' ? (
            <>
              <View style={styles.logoBlock}>
                <Text style={styles.logoText}>NISCHINT</Text>
                <NischintLogo size={48} />
              </View>

              <View style={styles.content}>
                <Text style={styles.title}>Let's Get Started</Text>
                <Text style={styles.subtitle}>Enter your phone number to continue.</Text>

                <Text style={styles.label}>MOBILE NUMBER</Text>
                <Pressable onPress={() => inputRef.current?.focus()} style={[styles.phoneBox, canContinue && styles.phoneBoxActive]}>
                  <View style={styles.countryBox}>
                    <Ionicons name="globe-outline" size={18} color="#64748B" />
                    <Text style={styles.countryText}>IN</Text>
                    <Text style={styles.dialText}>+91</Text>
                    <Ionicons name="chevron-down" size={16} color="#94A3B8" />
                  </View>
                  <View style={styles.divider} />
                  <View style={styles.inputBox}>
                    <Ionicons name="call-outline" size={20} color="#CBD5E1" />
                    <TextInput
                      ref={inputRef}
                      style={styles.phoneInput}
                      placeholder="Enter phone number"
                      placeholderTextColor="#CBD5E1"
                      keyboardType="phone-pad"
                      value={digits}
                      onChangeText={setPhone}
                      maxLength={10}
                      testID="register-phone-input"
                    />
                  </View>
                </Pressable>

                <Text style={styles.helper}>We'll send a one-time verification code to this number.</Text>
              </View>

              <View style={styles.bottom}>
                <TouchableOpacity
                  activeOpacity={0.86}
                  style={[styles.continueButton, !canContinue && styles.continueDisabled]}
                  onPress={handleContinue}
                  testID="register-submit-btn"
                >
                  <Text style={styles.continueText}>Continue</Text>
                </TouchableOpacity>

                <Text style={styles.terms}>
                  By continuing, you agree to our <Text style={styles.link}>Terms of Use</Text> and <Text style={styles.link}>Privacy Policy</Text>
                </Text>
              </View>
            </>
          ) : (
            <>
              <View style={styles.otpLogo}>
                <NischintLogo size={42} />
              </View>
              <View style={styles.otpHero}>
                <LinearGradient colors={['#22D3EE', '#22E0D0']} style={styles.otpIcon}>
                  <Ionicons name="notifications-outline" size={34} color="#FFFFFF" />
                </LinearGradient>
                <Text style={styles.otpTitle}>Enter the Code Sent to Your Phone</Text>
                <Text style={styles.otpSubtitle}>We've sent a 6-digit code to +91 {digits}</Text>
                <Text style={styles.otpHint}>Code expires in 10:00</Text>
              </View>

              <Pressable onPress={() => otpRef.current?.focus()} style={styles.otpRow}>
                {[0, 1, 2, 3, 4, 5].map((index) => (
                  <View key={index} style={[styles.otpBox, otp[index] && styles.otpBoxFilled]}>
                    <Text style={styles.otpDigit}>{otp[index] || ''}</Text>
                  </View>
                ))}
                <TextInput
                  ref={otpRef}
                  value={otp}
                  onChangeText={(value) => setOtp(value.replace(/\D/g, '').slice(0, 6))}
                  keyboardType="number-pad"
                  maxLength={6}
                  style={styles.hiddenOtpInput}
                  testID="register-otp-input"
                />
              </Pressable>

              <Text style={styles.resendText}>Didn't receive it? <Text style={styles.link}>Resend in 00:29</Text></Text>

              <View style={styles.bottom}>
                <TouchableOpacity
                  activeOpacity={0.86}
                  style={[styles.continueButton, otp.length < 6 && styles.continueDisabled]}
                  onPress={handleVerify}
                  testID="register-submit-btn"
                >
                  <Text style={styles.continueText}>Verify & Continue</Text>
                </TouchableOpacity>
              </View>
            </>
          )}
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: {
    flex: 1,
    backgroundColor: '#FFFFFF',
  },
  topRule: {
    height: 5,
  },
  flex: {
    flex: 1,
  },
  scroll: {
    flexGrow: 1,
    paddingHorizontal: 28,
    paddingTop: 34,
    paddingBottom: 140,
  },
  backButton: {
    width: 48,
    height: 48,
    borderRadius: 24,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#F1F5F9',
  },
  logoBlock: {
    marginTop: 46,
    marginLeft: 8,
    width: 84,
    alignItems: 'center',
  },
  logoText: {
    color: '#0891B2',
    fontSize: 10,
    lineHeight: 13,
    fontWeight: '900',
    letterSpacing: 1,
  },
  content: {
    marginTop: 54,
  },
  title: {
    color: '#07111F',
    fontSize: 37,
    lineHeight: 44,
    fontWeight: '900',
    letterSpacing: 0,
  },
  subtitle: {
    color: '#5F6B7A',
    fontSize: 17,
    lineHeight: 24,
    fontWeight: '600',
    marginTop: 14,
  },
  label: {
    color: '#111827',
    fontSize: 13,
    lineHeight: 17,
    fontWeight: '900',
    letterSpacing: 2,
    marginTop: 38,
    marginBottom: 12,
  },
  phoneBox: {
    minHeight: 72,
    borderRadius: 22,
    borderWidth: 2,
    borderColor: '#38BDF8',
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#FFFFFF',
    shadowColor: '#0EA5E9',
    shadowOpacity: 0.12,
    shadowOffset: { width: 0, height: 10 },
    shadowRadius: 20,
    elevation: 3,
  },
  phoneBoxActive: {
    borderColor: '#0891B2',
  },
  countryBox: {
    width: 132,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
  },
  countryText: {
    color: '#111827',
    fontSize: 16,
    fontWeight: '900',
  },
  dialText: {
    color: '#111827',
    fontSize: 16,
    fontWeight: '900',
  },
  divider: {
    width: 1,
    height: '100%',
    backgroundColor: '#E2E8F0',
  },
  inputBox: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    paddingHorizontal: 18,
  },
  phoneInput: {
    flex: 1,
    color: '#0F172A',
    fontSize: 17,
    lineHeight: 22,
    fontWeight: '700',
    minWidth: 0,
  },
  helper: {
    color: '#8A94A3',
    fontSize: 13,
    lineHeight: 20,
    fontWeight: '600',
    marginTop: 16,
  },
  bottom: {
    marginTop: 'auto',
  },
  continueButton: {
    minHeight: 70,
    borderRadius: 20,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#20C7F3',
  },
  continueDisabled: {
    backgroundColor: '#BAEEF8',
  },
  continueText: {
    color: '#FFFFFF',
    fontSize: 18,
    lineHeight: 24,
    fontWeight: '900',
  },
  terms: {
    color: '#7C8797',
    fontSize: 12,
    lineHeight: 18,
    fontWeight: '600',
    textAlign: 'center',
    marginTop: 26,
  },
  link: {
    color: '#0E7490',
    fontWeight: '900',
  },
  otpHero: {
    alignItems: 'center',
    marginTop: 42,
    paddingHorizontal: 12,
  },
  otpLogo: {
    alignSelf: 'center',
    marginTop: 28,
  },
  otpIcon: {
    width: 72,
    height: 72,
    borderRadius: 22,
    alignItems: 'center',
    justifyContent: 'center',
    shadowColor: '#0EA5E9',
    shadowOpacity: 0.25,
    shadowOffset: { width: 0, height: 12 },
    shadowRadius: 22,
    elevation: 6,
  },
  otpTitle: {
    color: '#111827',
    fontSize: 22,
    lineHeight: 28,
    fontWeight: '900',
    textAlign: 'center',
    marginTop: 38,
    maxWidth: 320,
  },
  otpSubtitle: {
    color: '#667085',
    fontSize: 14,
    lineHeight: 21,
    fontWeight: '600',
    textAlign: 'center',
    marginTop: 10,
    maxWidth: 280,
  },
  otpHint: {
    color: '#0EA5E9',
    fontSize: 12,
    lineHeight: 17,
    fontWeight: '800',
    marginTop: 8,
  },
  otpRow: {
    flexDirection: 'row',
    justifyContent: 'center',
    gap: 10,
    marginTop: 40,
  },
  otpBox: {
    width: 46,
    height: 56,
    borderRadius: 15,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#FFFFFF',
    borderWidth: 1.5,
    borderColor: '#E2E8F0',
  },
  otpBoxFilled: {
    borderColor: '#20C7F3',
    backgroundColor: '#F0FDFA',
  },
  otpDigit: {
    color: '#0F172A',
    fontSize: 20,
    lineHeight: 25,
    fontWeight: '900',
  },
  hiddenOtpInput: {
    position: 'absolute',
    width: 1,
    height: 1,
    opacity: 0,
  },
  resendText: {
    color: '#8A94A3',
    fontSize: 12,
    lineHeight: 18,
    fontWeight: '700',
    textAlign: 'center',
    marginTop: 20,
  },
});
