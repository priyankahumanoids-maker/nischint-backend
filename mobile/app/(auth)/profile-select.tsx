import { View, Text, TouchableOpacity, StyleSheet } from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useAuthStore } from '@/stores/authStore';
import { colors, spacing, fontSize, radius, shadows } from '@/theme';

const PROFILES = [
  {
    key: 'women' as const,
    icon: 'shield-half-outline' as const,
    label: 'Women Safety',
    desc: 'Late-night travel, safe routes, live sharing',
    color: colors.accentPink,
  },
  {
    key: 'kids' as const,
    icon: 'happy-outline' as const,
    label: 'Kids Safety',
    desc: 'School commute, guardian alerts, geo-fencing',
    color: colors.primary,
  },
  {
    key: 'parents' as const,
    icon: 'heart-outline' as const,
    label: 'Family Safety',
    desc: 'Elderly monitoring, fall detection, wellness',
    color: colors.verySafe,
  },
];

export default function ProfileSelectScreen() {
  const { setProfileMode, profileMode } = useAuthStore();
  const router = useRouter();

  const handleSelect = async (mode: 'women' | 'kids' | 'parents') => {
    await setProfileMode(mode);
    router.replace('/(tabs)/home');
  };

  return (
    <SafeAreaView style={styles.safe}>
      <View style={styles.container}>
        <Text style={styles.title}>Choose Your Profile</Text>
        <Text style={styles.subtitle}>
          Select who you're keeping safe. You can change this anytime.
        </Text>

        <View style={styles.cards}>
          {PROFILES.map((p) => (
            <TouchableOpacity
              key={p.key}
              style={[
                styles.card,
                profileMode === p.key && { borderColor: p.color, borderWidth: 2 },
              ]}
              onPress={() => handleSelect(p.key)}
              testID={`profile-${p.key}-btn`}
            >
              <View style={[styles.iconCircle, { backgroundColor: p.color + '20' }]}>
                <Ionicons name={p.icon} size={32} color={p.color} />
              </View>
              <View style={styles.cardText}>
                <Text style={styles.cardLabel}>{p.label}</Text>
                <Text style={styles.cardDesc}>{p.desc}</Text>
              </View>
              <Ionicons name="chevron-forward" size={20} color={colors.textMuted} />
            </TouchableOpacity>
          ))}
        </View>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.bg },
  container: { flex: 1, padding: spacing['3xl'], justifyContent: 'center' },
  title: { fontSize: fontSize['3xl'], fontWeight: '800', color: colors.textPrimary, textAlign: 'center' },
  subtitle: { fontSize: fontSize.md, color: colors.textSecondary, textAlign: 'center', marginTop: spacing.sm, marginBottom: spacing['4xl'] },
  cards: { gap: spacing.lg },
  card: {
    flexDirection: 'row', alignItems: 'center',
    backgroundColor: colors.bgCard, borderRadius: radius.lg,
    padding: spacing.xl, borderWidth: 1, borderColor: colors.border,
    ...shadows.md,
  },
  iconCircle: {
    width: 56, height: 56, borderRadius: 28,
    justifyContent: 'center', alignItems: 'center',
    marginRight: spacing.lg,
  },
  cardText: { flex: 1 },
  cardLabel: { fontSize: fontSize.lg, fontWeight: '700', color: colors.textPrimary },
  cardDesc: { fontSize: fontSize.sm, color: colors.textSecondary, marginTop: 2 },
});
