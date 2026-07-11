// Root layout — manages auth state, routing, and global safety layer
// IMPORTANT: backgroundLocation must be imported first to register the task before app renders
import '@/services/backgroundLocation';
// HC-01 Day 3 — register the wearable sync TaskManager task at boot so
// it's known to the OS even before the user is signed in. Registration
// of the BackgroundFetch *schedule* happens conditionally below (only
// after auth + only when Health Connect permissions are granted).
import '@/tasks/wearableSyncTask';
// NISCH-008 — register WebRTC globals once, at app boot. The shim
// adds `RTCPeerConnection`, `MediaStream`, etc. to the global scope
// so any module can use them. Safe to call multiple times.
import { registerGlobals as _registerWebRTCGlobals } from 'react-native-webrtc';
_registerWebRTCGlobals();
import { useEffect } from 'react';
import { Stack, useRouter, useSegments } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import * as SystemUI from 'expo-system-ui';
import { StatusBar } from 'expo-status-bar';
import { LogBox, View, Text, ActivityIndicator, StyleSheet } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { useAuthStore } from '@/stores/authStore';
import { SafetyProvider } from '@/providers/SafetyProvider';
import { useOTAUpdates } from '@/hooks/useOTAUpdates';
import { StreamBanner } from '@/components/incidents/StreamBanner';
import { ConsentSheet } from '@/components/ConsentSheet';
import { colors } from '@/theme';

SplashScreen.preventAutoHideAsync().catch(() => {});
SystemUI.setBackgroundColorAsync('#061525').catch(() => {});

if (__DEV__) {
  LogBox.ignoreAllLogs(true);
}

function AuthGuard({ children }: { children: React.ReactNode }) {
  const { token, user, isReady, isLoading } = useAuthStore();
  const segments = useSegments();
  const router = useRouter();

  // HC-01 Day 3 — after the user is authenticated, register the
  // 10-minute wearable BackgroundFetch schedule, but only when the
  // user has previously granted Health Connect permission. We avoid
  // touching BackgroundFetch on iOS (Day 3 ships Android-only) so we
  // don't waste a registration slot.
  useEffect(() => {
    if (!isReady || isLoading || !token) return;
    let cancelled = false;
    (async () => {
      try {
        const { Platform } = await import('react-native');
        if (Platform.OS !== 'android') return;
        const { isHealthConnectGranted } = await import('@/services/healthConnectStorage');
        const granted = await isHealthConnectGranted();
        if (!granted || cancelled) return;
        const { registerWearableSync } = await import('@/tasks/wearableSyncTask');
        await registerWearableSync();
        console.log('[HC-01] WEARABLE_SYNC background task registered');
      } catch (err) {
        console.warn('[HC-01] WEARABLE_SYNC register failed:', err);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token, isReady, isLoading]);

  useEffect(() => {
    if (!isReady || isLoading) return;

    const inAuth = segments[0] === '(auth)';
    const inIntro = segments[0] === 'intro';
    const inOnboarding = segments[0] === 'onboarding';

    // Normalize role — handle all backend variations
    const role = (user?.role || '').toLowerCase();
    const isAuthenticated = !!token && !!role;

    // Debug log — keep this for testing
    console.log('[AUTH] Guard — role:', role, '| token:', !!token, '| segment:', segments[0]);

    if (!isAuthenticated) {
      // Not authenticated -> show the branded intro before auth.
      if (!inAuth && !inIntro && !inOnboarding) {
        router.replace('/intro');
      }
    } else if (inAuth || inIntro || inOnboarding) {
      // Authenticated but on auth screen → go to main app
      router.replace('/(tabs)/home');
    }
  }, [token, user, isReady, isLoading, segments]);

  // Show loading screen while auth state is being determined
  if (!isReady || isLoading) {
    return (
      <View style={styles.loader}>
        <ActivityIndicator size="large" color={colors.primary} />
        <Text style={styles.loaderText}>Loading...</Text>
      </View>
    );
  }

  return <>{children}</>;
}

export default function RootLayout() {
  const { loadToken } = useAuthStore();
  useOTAUpdates();

  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        await loadToken();
      } finally {
        if (mounted) {
          SplashScreen.hideAsync().catch(() => {});
        }
      }
    })();
    return () => {
      mounted = false;
    };
  }, [loadToken]);

  return (
    <SafeAreaProvider>
      <SafetyProvider>
        <AuthGuard>
          <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: colors.bg } }}>
            <Stack.Screen name="intro" />
            <Stack.Screen name="onboarding" />
            <Stack.Screen name="(auth)" />
            <Stack.Screen name="(tabs)" />
            <Stack.Screen name="incident-timeline" options={{ presentation: 'card' }} />
            <Stack.Screen name="stream-caller" options={{ presentation: 'modal', gestureEnabled: false }} />
            <Stack.Screen name="stream-listener" options={{ presentation: 'card' }} />
            <Stack.Screen name="health-history" options={{ presentation: 'card' }} />
            <Stack.Screen name="privacy" options={{ presentation: 'card' }} />
          </Stack>
          {/* NISCH-008 — global child-side stream offer banner.
              Lives outside the AuthGuard child so it doesn't unmount
              on tab transitions; visible only when the child SSE
              hook fires `stream_offer`. */}
          <StreamBanner />
        </AuthGuard>
        {/* DPDP-04-MOB — global pre-permission consent half-modal.
            Lives outside AuthGuard so it can also gate consent on
            the auth screens (e.g., push token registration). */}
        <ConsentSheet />
      </SafetyProvider>
      <StatusBar style="light" />
    </SafeAreaProvider>
  );
}

const styles = StyleSheet.create({
  loader: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: '#061525',
  },
  loaderText: {
    color: colors.textMuted,
    marginTop: 12,
    fontSize: 14,
  },
});
