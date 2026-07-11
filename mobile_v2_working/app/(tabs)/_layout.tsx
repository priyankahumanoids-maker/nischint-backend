// Tab Navigator — role-based tab visibility
import { Tabs } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { SafeAreaView } from 'react-native-safe-area-context';
import { colors, fontSize } from '@/theme';
import { useAuthStore } from '@/stores/authStore';

export default function TabLayout() {
  const { user, profileMode } = useAuthStore();
  // Server role ONLY — no profile_type
  const role = (user?.role || '').toLowerCase().trim();
  const isGuardian = ['guardian', 'parent', 'parents', 'parents_care', 'caregiver', 'family'].includes(role);
  const isChild = ['child', 'kid', 'kids', 'children', 'woman', 'women', 'senior', 'elderly'].includes(role);
  const isProtectedMode = ['kids', 'women', 'senior', 'family'].includes(profileMode);

  console.log('[AUTH] TabLayout role:', role, '| isGuardian:', isGuardian, '| isChild:', isChild);

  if (profileMode === 'women') {
    return (
      <SafeAreaView style={{ flex: 1, backgroundColor: colors.bg }} edges={['bottom', 'left', 'right']}>
        <Tabs
          initialRouteName="home"
          screenOptions={{
            headerShown: false,
            tabBarStyle: {
              backgroundColor: colors.bgCard,
              borderTopColor: colors.border,
              borderTopWidth: 1,
              height: 78,
              paddingBottom: 10,
              paddingTop: 6,
            },
            tabBarActiveTintColor: colors.primary,
            tabBarInactiveTintColor: colors.textMuted,
            tabBarLabelStyle: { fontSize: fontSize.xs, fontWeight: '700' },
          }}
        >
          <Tabs.Screen
            name="home"
            options={{
              title: 'SOS',
              tabBarIcon: ({ color, size, focused }) => (
                <Ionicons name={focused ? 'flash' : 'flash-outline'} size={focused ? size + 8 : size} color={focused ? '#EF4444' : color} />
              ),
            }}
          />
          <Tabs.Screen
            name="guardian"
            options={{
              title: 'Safe Walk',
              tabBarIcon: ({ color, size }) => <Ionicons name="walk-outline" size={size} color={color} />,
            }}
          />
          <Tabs.Screen
            name="alerts"
            options={{
              title: 'Protection',
              tabBarIcon: ({ color, size }) => <Ionicons name="shield-outline" size={size} color={color} />,
            }}
          />
          <Tabs.Screen
            name="journey"
            options={{
              title: 'Route',
              tabBarIcon: ({ color, size }) => <Ionicons name="location-outline" size={size} color={color} />,
            }}
          />
          <Tabs.Screen
            name="settings"
            options={{
              title: 'Settings',
              tabBarIcon: ({ color, size }) => <Ionicons name="settings-outline" size={size} color={color} />,
            }}
          />
          <Tabs.Screen name="safety-score" options={{ href: null }} />
          <Tabs.Screen name="incidents" options={{ href: null }} />
        </Tabs>
      </SafeAreaView>
    );
  }

  if (isProtectedMode) {
    return (
      <SafeAreaView style={{ flex: 1, backgroundColor: colors.bg }} edges={['bottom', 'left', 'right']}>
        <Tabs
          initialRouteName="home"
          screenOptions={{
            headerShown: false,
            tabBarStyle: {
              backgroundColor: colors.bgCard,
              borderTopColor: colors.border,
              borderTopWidth: 1,
              height: 78,
              paddingBottom: 12,
              paddingTop: 6,
            },
            tabBarActiveTintColor: colors.primary,
            tabBarInactiveTintColor: colors.textMuted,
            tabBarLabelStyle: { fontSize: fontSize.xs, fontWeight: '700' },
          }}
        >
          <Tabs.Screen
            name="alerts"
            options={{
              title: 'Protection',
              tabBarIcon: ({ color, size }) => <Ionicons name="shield-outline" size={size} color={color} />,
            }}
          />
          <Tabs.Screen
            name="home"
            options={{
              title: 'SOS',
              tabBarIcon: ({ color, size, focused }) => (
                <Ionicons name={focused ? 'flash' : 'flash-outline'} size={focused ? size + 8 : size} color={focused ? '#EF4444' : color} />
              ),
            }}
          />
          <Tabs.Screen
            name="guardian"
            options={{
              title: 'Route',
              tabBarIcon: ({ color, size }) => <Ionicons name="location-outline" size={size} color={color} />,
            }}
          />
          <Tabs.Screen
            name="settings"
            options={{
              title: 'Settings',
              tabBarIcon: ({ color, size }) => <Ionicons name="settings-outline" size={size} color={color} />,
            }}
          />
          <Tabs.Screen name="safety-score" options={{ href: null }} />
          <Tabs.Screen name="incidents" options={{ href: null }} />
          <Tabs.Screen name="journey" options={{ href: null }} />
        </Tabs>
      </SafeAreaView>
    );
  }

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
            title: isProtectedMode ? 'SOS' : 'Home',
            tabBarIcon: ({ color, size }) => (
              <Ionicons name={isProtectedMode ? 'flash-outline' : 'home-outline'} size={size} color={color} />
            ),
          }}
        />
        <Tabs.Screen
          name="guardian"
          options={{
            title: isProtectedMode ? 'Route' : 'Family',
            tabBarIcon: ({ color, size }) => <Ionicons name={isProtectedMode ? 'navigate-outline' : 'people-outline'} size={size} color={color} />,
          }}
        />
        <Tabs.Screen
          name="safety-score"
          options={{
            title: 'Score',
            tabBarIcon: ({ color, size }) => <Ionicons name="analytics" size={size} color={color} />,
            href: null,
          }}
        />
        <Tabs.Screen
          name="alerts"
          options={{
            title: isProtectedMode ? 'Protection' : 'Alerts',
            tabBarIcon: ({ color, size }) => <Ionicons name={isProtectedMode ? 'shield-checkmark-outline' : 'notifications-outline'} size={size} color={color} />,
          }}
        />
        <Tabs.Screen
          name="incidents"
          options={{
            title: isProtectedMode ? 'Health' : 'Protection',
            tabBarIcon: ({ color, size }) => (
              <Ionicons name={isProtectedMode ? 'heart-outline' : 'shield-outline'} size={size} color={color} />
            ),
            // NISCH-007: guardian-only feed surface. Children/woman/senior
            // roles don't see this tab — they see their own home.
          }}
        />
        <Tabs.Screen
          name="settings"
          options={{
            title: 'Settings',
            tabBarIcon: ({ color, size }) => (
              <Ionicons name="settings-outline" size={size} color={color} />
            ),
          }}
        />
        <Tabs.Screen
          name="journey"
          options={{
            title: 'Journey',
            tabBarIcon: ({ color, size }) => <Ionicons name="navigate-outline" size={size} color={color} />,
            href: isProtectedMode ? undefined : null,
          }}
        />
      </Tabs>
    </SafeAreaView>
  );
}
