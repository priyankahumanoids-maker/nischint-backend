// Tab Navigator — role-based tab visibility
import { Tabs } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { SafeAreaView } from 'react-native-safe-area-context';
import { colors, fontSize } from '@/theme';
import { useAuthStore } from '@/stores/authStore';

export default function TabLayout() {
  const { user } = useAuthStore();
  // Server role ONLY — no profile_type
  const role = (user?.role || '').toLowerCase().trim();
  const isGuardian = ['guardian', 'parent', 'parents', 'parents_care', 'caregiver', 'family'].includes(role);
  const isChild = ['child', 'kid', 'kids', 'children', 'woman', 'women', 'senior', 'elderly'].includes(role);

  console.log('[AUTH] TabLayout role:', role, '| isGuardian:', isGuardian, '| isChild:', isChild);

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: colors.bg }} edges={['bottom', 'left', 'right']}>
      <Tabs
        screenOptions={{
          headerShown: false,
          tabBarStyle: {
            backgroundColor: colors.bgCard,
            borderTopColor: colors.border,
            borderTopWidth: 1,
            height: 70,
            paddingBottom: 12,
            paddingTop: 6,
          },
          tabBarActiveTintColor: colors.primary,
          tabBarInactiveTintColor: colors.textMuted,
          tabBarLabelStyle: { fontSize: fontSize.xs, fontWeight: '600' },
        }}
      >
        <Tabs.Screen
          name="home"
          options={{
            title: isGuardian ? 'Family' : 'Home',
            tabBarIcon: ({ color, size }) => (
              <Ionicons name={isGuardian ? 'people' : 'shield-checkmark'} size={size} color={color} />
            ),
          }}
        />
        <Tabs.Screen
          name="journey"
          options={{
            title: 'Journey',
            tabBarIcon: ({ color, size }) => <Ionicons name="navigate" size={size} color={color} />,
            href: isGuardian ? null : '/(tabs)/journey',
          }}
        />
        <Tabs.Screen
          name="safety-score"
          options={{
            title: 'Score',
            tabBarIcon: ({ color, size }) => <Ionicons name="analytics" size={size} color={color} />,
            href: ['woman', 'women'].includes(role) ? '/(tabs)/safety-score' : null,
          }}
        />
        <Tabs.Screen
          name="alerts"
          options={{
            title: 'Alerts',
            tabBarIcon: ({ color, size }) => <Ionicons name="warning" size={size} color={color} />,
          }}
        />
        <Tabs.Screen
          name="incidents"
          options={{
            title: 'Incidents',
            tabBarIcon: ({ color, size }) => (
              <Ionicons name="pulse" size={size} color={color} />
            ),
            // NISCH-007: guardian-only feed surface. Children/woman/senior
            // roles don't see this tab — they see their own home.
            href: isGuardian ? '/(tabs)/incidents' : null,
          }}
        />
        <Tabs.Screen
          name="guardian"
          options={{
            title: isGuardian ? 'Settings' : 'Share',
            tabBarIcon: ({ color, size }) => (
              <Ionicons name={isGuardian ? 'settings-outline' : 'share-social'} size={size} color={color} />
            ),
          }}
        />
      </Tabs>
    </SafeAreaView>
  );
}
