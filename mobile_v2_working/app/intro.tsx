import { useEffect, useRef } from 'react';
import {
  Animated,
  Easing,
  Image,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { useRouter } from 'expo-router';
import { StatusBar } from 'expo-status-bar';

const INTRO_DURATION_MS = 3_000;
const shieldLogo = require('../assets/nischint-shield.png');

export default function IntroScreen() {
  const router = useRouter();
  const progress = useRef(new Animated.Value(0)).current;
  const pulse = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    Animated.timing(progress, {
      toValue: 1,
      duration: INTRO_DURATION_MS,
      easing: Easing.linear,
      useNativeDriver: false,
    }).start(({ finished }) => {
      if (finished) {
        router.replace('/onboarding');
      }
    });

    const pulseLoop = Animated.loop(
      Animated.sequence([
        Animated.timing(pulse, {
          toValue: 1,
          duration: 2400,
          easing: Easing.out(Easing.quad),
          useNativeDriver: true,
        }),
        Animated.timing(pulse, {
          toValue: 0,
          duration: 0,
          useNativeDriver: true,
        }),
      ]),
    );
    pulseLoop.start();

    return () => {
      progress.stopAnimation();
      pulseLoop.stop();
    };
  }, [progress, pulse, router]);

  const progressWidth = progress.interpolate({
    inputRange: [0, 1],
    outputRange: ['0%', '100%'],
  });
  const pulseScale = pulse.interpolate({
    inputRange: [0, 1],
    outputRange: [0.92, 1.18],
  });
  const pulseOpacity = pulse.interpolate({
    inputRange: [0, 1],
    outputRange: [0.28, 0.02],
  });

  return (
    <View style={styles.screen}>
      <StatusBar style="light" />
      <LinearGradient
        colors={['#071225', '#06233B', '#063E42', '#032216']}
        locations={[0, 0.43, 0.72, 1]}
        style={StyleSheet.absoluteFill}
      />

      <View style={styles.ringStage}>
        <View style={[styles.ring, styles.ringOuter]} />
        <View style={[styles.ring, styles.ringMiddle]} />
        <View style={[styles.ring, styles.ringInner]} />
        <Animated.View
          style={[
            styles.glow,
            {
              opacity: pulseOpacity,
              transform: [{ scale: pulseScale }],
            },
          ]}
        />
      </View>

      <View style={styles.brandBlock}>
        <Image source={shieldLogo} resizeMode="contain" style={styles.logoShield} />

        <Text style={styles.name}>NISCHINT</Text>

        <View style={styles.taglineRow}>
          <View style={styles.rule} />
          <Text style={styles.tagline}>FAMILY SAFETY PLATFORM</Text>
          <View style={styles.rule} />
        </View>
      </View>

      <View style={styles.progressTrack}>
        <Animated.View style={[styles.progressFill, { width: progressWidth }]} />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#071225',
    overflow: 'hidden',
  },
  ringStage: {
    position: 'absolute',
    width: 420,
    height: 420,
    alignItems: 'center',
    justifyContent: 'center',
  },
  ring: {
    position: 'absolute',
    borderColor: 'rgba(125, 211, 252, 0.08)',
    borderWidth: 1,
  },
  ringOuter: {
    width: 410,
    height: 410,
    borderRadius: 205,
  },
  ringMiddle: {
    width: 318,
    height: 318,
    borderRadius: 159,
  },
  ringInner: {
    width: 232,
    height: 232,
    borderRadius: 116,
  },
  glow: {
    position: 'absolute',
    width: 270,
    height: 270,
    borderRadius: 135,
    backgroundColor: '#0EA5E9',
  },
  brandBlock: {
    alignItems: 'center',
    paddingHorizontal: 28,
  },
  logoShield: {
    width: 134,
    height: 114,
    marginBottom: 42,
    shadowColor: '#22D3EE',
    shadowOffset: { width: 0, height: 16 },
    shadowOpacity: 0.28,
    shadowRadius: 30,
    elevation: 10,
  },
  name: {
    color: '#FFFFFF',
    fontSize: 46,
    lineHeight: 52,
    fontWeight: '900',
    letterSpacing: 8,
    textAlign: 'center',
  },
  taglineRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: 12,
    gap: 12,
  },
  tagline: {
    color: 'rgba(226, 232, 240, 0.66)',
    fontSize: 14,
    fontWeight: '800',
    letterSpacing: 5,
    textAlign: 'center',
  },
  rule: {
    width: 42,
    height: 1,
    backgroundColor: 'rgba(226, 232, 240, 0.22)',
  },
  progressTrack: {
    position: 'absolute',
    bottom: 62,
    width: 100,
    height: 2,
    backgroundColor: 'rgba(226, 232, 240, 0.18)',
    overflow: 'hidden',
  },
  progressFill: {
    height: 2,
    backgroundColor: '#22E0D0',
  },
});
