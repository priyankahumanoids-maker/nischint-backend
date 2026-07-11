import { useState } from 'react';
import {
  View, Text, TextInput, TouchableOpacity, StyleSheet,
  KeyboardAvoidingView, Platform, ScrollView, Alert,
} from 'react-native';
import { useRouter, Link } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useAuthStore } from '@/stores/authStore';
import { colors, spacing, fontSize, radius } from '@/theme';

export default function RegisterScreen() {
  const [fullName, setFullName] = useState('');
  const [email, setEmail] = useState('');
  const [phone, setPhone] = useState('');
  const [password, setPassword] = useState('');
  const { register, isLoading } = useAuthStore();
  const router = useRouter();

  const handleRegister = async () => {
    if (!fullName || !email || !password) {
      Alert.alert('Error', 'Please fill all required fields');
      return;
    }
    if (password.length < 8) {
      Alert.alert('Error', 'Password must be at least 8 characters');
      return;
    }
    try {
      await register({ email: email.trim(), password, full_name: fullName.trim(), phone: phone.trim() || undefined });
      router.replace('/(auth)/profile-select');
    } catch (e: any) {
      // Extract the most useful error message from the server response
      let msg = 'Registration failed. Please try again.';
      if (e.response?.data?.detail) {
        const detail = e.response.data.detail;
        if (typeof detail === 'string') {
          msg = detail;
        } else if (Array.isArray(detail)) {
          // Pydantic validation errors come as an array
          msg = detail.map((d: any) => d.msg || JSON.stringify(d)).join('\n');
        }
      } else if (e.message) {
        msg = e.message;
      }
      Alert.alert('Registration Error', msg);
    }
  };

  return (
    <SafeAreaView style={styles.safe}>
      <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
          <Text style={styles.title}>Create Account</Text>
          <Text style={styles.subtitle}>Join NISCHINT for always-on safety</Text>

          <View style={styles.form}>
            <InputRow icon="person-outline" placeholder="Full Name" value={fullName} onChangeText={setFullName} testID="register-name-input" />
            <InputRow icon="mail-outline" placeholder="Email" value={email} onChangeText={setEmail} keyboardType="email-address" testID="register-email-input" />
            <InputRow icon="call-outline" placeholder="Phone (optional)" value={phone} onChangeText={setPhone} keyboardType="phone-pad" testID="register-phone-input" />
            <InputRow icon="lock-closed-outline" placeholder="Password" value={password} onChangeText={setPassword} secure testID="register-password-input" />

            <TouchableOpacity
              style={[styles.btn, isLoading && styles.btnDisabled]}
              onPress={handleRegister}
              disabled={isLoading}
              testID="register-submit-btn"
            >
              <Text style={styles.btnText}>{isLoading ? 'Creating...' : 'Create Account'}</Text>
            </TouchableOpacity>

            <View style={styles.row}>
              <Text style={styles.rowText}>Already have an account? </Text>
              <Link href="/(auth)/login" asChild>
                <TouchableOpacity><Text style={styles.link}>Sign In</Text></TouchableOpacity>
              </Link>
            </View>
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

function InputRow({ icon, placeholder, value, onChangeText, keyboardType, secure, testID }: any) {
  return (
    <View style={styles.inputWrap}>
      <Ionicons name={icon} size={20} color={colors.textMuted} style={{ marginRight: spacing.md }} />
      <TextInput
        style={styles.input}
        placeholder={placeholder}
        placeholderTextColor={colors.textMuted}
        value={value}
        onChangeText={onChangeText}
        autoCapitalize="none"
        keyboardType={keyboardType}
        secureTextEntry={secure}
        testID={testID}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.bg },
  flex: { flex: 1 },
  scroll: { flexGrow: 1, justifyContent: 'center', padding: spacing['3xl'] },
  title: { fontSize: fontSize['3xl'], fontWeight: '800', color: colors.textPrimary, textAlign: 'center' },
  subtitle: { fontSize: fontSize.md, color: colors.textSecondary, textAlign: 'center', marginTop: spacing.xs, marginBottom: spacing['3xl'] },
  form: { gap: spacing.lg },
  inputWrap: {
    flexDirection: 'row', alignItems: 'center',
    backgroundColor: colors.bgInput, borderRadius: radius.lg,
    borderWidth: 1, borderColor: colors.border,
    paddingHorizontal: spacing.lg, height: 52,
  },
  input: { flex: 1, color: colors.textPrimary, fontSize: fontSize.md },
  btn: { backgroundColor: colors.primary, borderRadius: radius.lg, height: 52, justifyContent: 'center', alignItems: 'center', marginTop: spacing.sm },
  btnDisabled: { opacity: 0.6 },
  btnText: { color: colors.white, fontSize: fontSize.lg, fontWeight: '700' },
  row: { flexDirection: 'row', justifyContent: 'center', marginTop: spacing.xl },
  rowText: { color: colors.textSecondary, fontSize: fontSize.md },
  link: { color: colors.primary, fontSize: fontSize.md, fontWeight: '600' },
});
