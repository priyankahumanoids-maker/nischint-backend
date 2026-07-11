import { useEffect, useRef, useState } from 'react';
import {
  Animated,
  Dimensions,
  Image,
  ImageSourcePropType,
  ImageBackground,
  NativeScrollEvent,
  NativeSyntheticEvent,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { useRouter } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import FigmaOnboarding from '../components/FigmaOnboarding';

const { width } = Dimensions.get('window');
const shieldLogo = require('../assets/nischint-shield.png');

const slides = [
  {
    key: 'family',
    image: require('../assets/onboarding/family-native-bg.jpg'),
    eyebrow: 'Protected',
    title: 'Protect What\nMatters Most',
    subtitle: 'The people you love deserve to feel close, safe, and cared for.',
    note: 'Together, always connected',
    cta: 'Get Started',
    mode: 'family' as const,
  },
  {
    key: 'watching',
    image: require('../assets/onboarding/watching-native-bg.jpg'),
    eyebrow: 'Journey Safe',
    title: 'Always Watching\nOver Them',
    subtitle: "Every journey matters when it's someone you love.",
    note: '01 - CHILD',
    cta: 'Continue',
    mode: 'route' as const,
  },
  {
    key: 'help',
    image: require('../assets/onboarding/help-native-bg.jpg'),
    eyebrow: 'SOS',
    title: 'Help Arrives\nInstantly',
    subtitle: "Be there for the moments that can't wait.",
    note: 'Help is on the way',
    cta: 'Create Your Safety Network',
    mode: 'help' as const,
  },
];

type VideoSlideProps = {
  slide: {
    image: ImageSourcePropType;
    eyebrow: string;
    title: string;
    subtitle: string;
    note: string;
    cta: string;
    mode: 'family' | 'route' | 'help';
  };
  index: number;
  activeIndex: number;
  onRegister: () => void;
  onSignIn: () => void;
};

function OnboardingSlide({ slide, index, activeIndex, onRegister, onSignIn }: VideoSlideProps) {
  const motion = useRef(new Animated.Value(0)).current;
  const isActive = index === activeIndex;

  useEffect(() => {
    if (!isActive) {
      motion.stopAnimation();
      motion.setValue(0);
      return;
    }

    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(motion, {
          toValue: 1,
          duration: 5200,
          useNativeDriver: true,
        }),
        Animated.timing(motion, {
          toValue: 0,
          duration: 5200,
          useNativeDriver: true,
        }),
      ]),
    );
    loop.start();
    return () => loop.stop();
  }, [isActive, motion]);

  const bgScale = motion.interpolate({
    inputRange: [0, 1],
    outputRange: [1, 1.07],
  });
  const bgShift = motion.interpolate({
    inputRange: [0, 1],
    outputRange: [0, -18],
  });
  const glowScale = motion.interpolate({
    inputRange: [0, 1],
    outputRange: [0.82, 1.16],
  });
  const glowOpacity = motion.interpolate({
    inputRange: [0, 1],
    outputRange: [0.24, 0.04],
  });

  return (
    <View style={styles.slide}>
      <Animated.View
        style={[
          styles.backgroundWrap,
          { transform: [{ scale: bgScale }, { translateY: bgShift }] },
        ]}
      >
        <ImageBackground source={slide.image} resizeMode="cover" style={styles.background} />
      </Animated.View>
      <LinearGradient
        colors={['rgba(3, 7, 18, 0.08)', 'rgba(3, 7, 18, 0.22)', 'rgba(3, 7, 18, 0.98)']}
        locations={[0, 0.52, 1]}
        style={StyleSheet.absoluteFill}
      />

      <View style={styles.brand}>
        <Image source={shieldLogo} resizeMode="contain" style={styles.logo} />
        <Text style={styles.brandText}>NISCHINT</Text>
      </View>

      {slide.mode === 'family' ? (
        <View style={styles.statusPill}>
          <View style={styles.statusDot} />
          <Text style={styles.statusText}>{slide.eyebrow}</Text>
        </View>
      ) : null}

      {slide.mode === 'help' ? (
        <View style={styles.guardianStack}>
          <GuardianCard title="Primary Guardian notified" icon="shield" />
          <GuardianCard title="Co-Guardian notified" icon="person" />
        </View>
      ) : null}

      <View style={styles.copy}>
        <Text style={styles.title}>{slide.title}</Text>
        <Text style={styles.subtitle}>{slide.subtitle}</Text>

        {slide.mode === 'route' ? (
          <View style={styles.routeCard}>
            <View style={styles.statusDot} />
            <View>
              <Text style={styles.routeTitle}>Route Normal</Text>
              <Text style={styles.routeText}>Child - Safe Walk On</Text>
            </View>
          </View>
        ) : null}

        {slide.mode === 'help' ? (
          <View style={styles.helpChip}>
            <View style={styles.statusDot} />
            <Text style={styles.helpText}>{slide.note}</Text>
          </View>
        ) : null}

        {slide.mode === 'family' ? <FamilyStrip /> : null}

        <View style={styles.metricRow}>
          <Text style={styles.metricText}>{slide.note}</Text>
          <View style={styles.metricLine}>
            <View style={styles.metricFill} />
          </View>
        </View>

        <Animated.View
          style={[
            styles.radar,
            {
              opacity: glowOpacity,
              transform: [{ scale: glowScale }],
            },
          ]}
        />
      </View>

      <View style={styles.bottom}>
        <View style={styles.dots}>
          {slides.map((item, dotIndex) => (
            <View
              key={item.key}
              style={[
                styles.dot,
                dotIndex === activeIndex && styles.dotActive,
              ]}
            />
          ))}
        </View>
        <Pressable accessibilityLabel="Create account" onPress={onRegister} style={styles.primaryButton}>
          <Text style={styles.primaryText}>{slide.cta}</Text>
        </Pressable>
        <Pressable accessibilityLabel="Sign in" onPress={onSignIn} style={styles.signInButton}>
          <Text style={styles.signInMuted}>Already have an account? </Text>
          <Text style={styles.signInText}>Sign In</Text>
        </Pressable>
      </View>
    </View>
  );
}

function GuardianCard({ title, icon }: { title: string; icon: 'shield' | 'person' }) {
  return (
    <View style={styles.guardianCard}>
      <View style={styles.guardianIcon}>
        <Text style={styles.guardianIconText}>{icon === 'shield' ? 'S' : 'G'}</Text>
      </View>
      <View style={styles.guardianCopy}>
        <Text style={styles.guardianTitle}>{title}</Text>
        <Text style={styles.guardianText}>Responding now</Text>
      </View>
      <View style={styles.guardianDot} />
    </View>
  );
}

function FamilyStrip() {
  const people = ['#DDE4EA', '#2563EB', '#10B981', '#7C3AED', '#F472B6'];
  return (
    <View style={styles.familyStrip}>
      {people.map((color, index) => (
        <View key={`${color}-${index}`} style={styles.person}>
          <View style={styles.head} />
          <View style={[styles.body, { backgroundColor: color }]} />
        </View>
      ))}
    </View>
  );
}

export default FigmaOnboarding;

function OnboardingScreen() {
  const router = useRouter();
  const scrollRef = useRef<ScrollView>(null);
  const [activeIndex, setActiveIndex] = useState(0);

  const goRegister = () => {
    router.replace('/(auth)/register');
  };

  const onScrollEnd = (event: NativeSyntheticEvent<NativeScrollEvent>) => {
    const nextIndex = Math.round(event.nativeEvent.contentOffset.x / width);
    setActiveIndex(Math.max(0, Math.min(slides.length - 1, nextIndex)));
  };

  return (
    <View style={styles.screen}>
      <StatusBar style="light" />
      <ScrollView
        ref={scrollRef}
        horizontal
        pagingEnabled
        bounces={false}
        showsHorizontalScrollIndicator={false}
        onMomentumScrollEnd={onScrollEnd}
        scrollEventThrottle={16}
      >
        {slides.map((slide, index) => (
          <OnboardingSlide
            key={slide.key}
            slide={slide}
            index={index}
            activeIndex={activeIndex}
            onRegister={goRegister}
            onSignIn={() => router.replace('/(auth)/login')}
          />
        ))}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: '#020617',
  },
  slide: {
    width,
    flex: 1,
    backgroundColor: '#020617',
    overflow: 'hidden',
  },
  backgroundWrap: {
    ...StyleSheet.absoluteFillObject,
  },
  background: {
    flex: 1,
  },
  brand: {
    position: 'absolute',
    top: 76,
    alignSelf: 'center',
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  logo: {
    width: 34,
    height: 30,
  },
  brandText: {
    color: '#FFFFFF',
    fontSize: 22,
    lineHeight: 26,
    fontWeight: '900',
    letterSpacing: 5,
    textShadowColor: 'rgba(0, 0, 0, 0.35)',
    textShadowOffset: { width: 0, height: 2 },
    textShadowRadius: 6,
  },
  statusPill: {
    position: 'absolute',
    top: 116,
    right: 28,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 9,
    paddingHorizontal: 16,
    paddingVertical: 10,
    borderRadius: 24,
    backgroundColor: 'rgba(15, 118, 178, 0.42)',
    borderWidth: 1,
    borderColor: 'rgba(125, 211, 252, 0.24)',
  },
  statusDot: {
    width: 10,
    height: 10,
    borderRadius: 5,
    backgroundColor: '#4ADE80',
  },
  statusText: {
    color: '#FFFFFF',
    fontSize: 15,
    fontWeight: '900',
  },
  guardianStack: {
    position: 'absolute',
    top: 118,
    left: 24,
    right: 24,
    gap: 12,
  },
  guardianCard: {
    minHeight: 72,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingHorizontal: 16,
    borderRadius: 20,
    backgroundColor: 'rgba(255, 255, 255, 0.22)',
    borderWidth: 1,
    borderColor: 'rgba(255, 255, 255, 0.2)',
  },
  guardianIcon: {
    width: 38,
    height: 38,
    borderRadius: 19,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: 'rgba(14, 165, 233, 0.24)',
  },
  guardianIconText: {
    color: '#38BDF8',
    fontSize: 20,
    fontWeight: '900',
  },
  guardianCopy: {
    flex: 1,
  },
  guardianTitle: {
    color: '#FFFFFF',
    fontSize: 16,
    lineHeight: 21,
    fontWeight: '900',
  },
  guardianText: {
    color: 'rgba(255, 255, 255, 0.64)',
    fontSize: 14,
    lineHeight: 18,
    fontWeight: '700',
  },
  guardianDot: {
    width: 10,
    height: 10,
    borderRadius: 5,
    backgroundColor: '#4ADE80',
  },
  copy: {
    position: 'absolute',
    left: 30,
    right: 30,
    bottom: 214,
  },
  title: {
    color: '#FFFFFF',
    fontSize: 40,
    lineHeight: 45,
    fontWeight: '900',
    textShadowColor: 'rgba(0, 0, 0, 0.35)',
    textShadowOffset: { width: 0, height: 2 },
    textShadowRadius: 10,
  },
  subtitle: {
    color: 'rgba(255, 255, 255, 0.78)',
    fontSize: 16,
    lineHeight: 25,
    fontWeight: '700',
    marginTop: 16,
    maxWidth: 330,
  },
  routeCard: {
    alignSelf: 'flex-start',
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    minHeight: 56,
    marginTop: 18,
    paddingHorizontal: 14,
    borderRadius: 16,
    backgroundColor: 'rgba(255, 255, 255, 0.22)',
    borderWidth: 1,
    borderColor: 'rgba(255, 255, 255, 0.18)',
  },
  routeTitle: {
    color: '#FFFFFF',
    fontSize: 15,
    fontWeight: '900',
  },
  routeText: {
    color: 'rgba(255, 255, 255, 0.68)',
    fontSize: 13,
    fontWeight: '700',
    marginTop: 2,
  },
  helpChip: {
    alignSelf: 'flex-start',
    flexDirection: 'row',
    alignItems: 'center',
    gap: 9,
    marginTop: 28,
    paddingHorizontal: 18,
    paddingVertical: 12,
    borderRadius: 24,
    backgroundColor: 'rgba(6, 78, 90, 0.42)',
    borderWidth: 1,
    borderColor: 'rgba(34, 211, 238, 0.26)',
  },
  helpText: {
    color: '#E2E8F0',
    fontSize: 15,
    fontWeight: '900',
  },
  familyStrip: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    gap: 13,
    marginTop: 20,
    paddingLeft: 6,
  },
  person: {
    width: 48,
    height: 72,
    alignItems: 'center',
    justifyContent: 'flex-end',
  },
  head: {
    width: 28,
    height: 28,
    borderRadius: 14,
    backgroundColor: '#E9B98F',
    marginBottom: -2,
  },
  body: {
    width: 34,
    height: 38,
    borderRadius: 8,
  },
  metricRow: {
    marginTop: 18,
    width: 120,
  },
  metricText: {
    color: 'rgba(255, 255, 255, 0.54)',
    fontSize: 12,
    lineHeight: 16,
    fontWeight: '900',
    letterSpacing: 1,
    textTransform: 'uppercase',
  },
  metricLine: {
    height: 2,
    marginTop: 8,
    backgroundColor: 'rgba(255, 255, 255, 0.2)',
  },
  metricFill: {
    width: '58%',
    height: 2,
    backgroundColor: '#22E0D0',
  },
  radar: {
    position: 'absolute',
    right: 42,
    bottom: 6,
    width: 158,
    height: 158,
    borderRadius: 79,
    borderWidth: 2,
    borderColor: '#22E0D0',
  },
  bottom: {
    position: 'absolute',
    left: 30,
    right: 30,
    bottom: 42,
    alignItems: 'center',
  },
  dots: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    marginBottom: 24,
  },
  dot: {
    width: 9,
    height: 9,
    borderRadius: 5,
    backgroundColor: 'rgba(255, 255, 255, 0.28)',
  },
  dotActive: {
    width: 34,
    backgroundColor: '#22E0D0',
  },
  primaryButton: {
    width: '100%',
    minHeight: 68,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: 24,
    backgroundColor: '#18CEF7',
    shadowColor: '#00B8F0',
    shadowOffset: { width: 0, height: 18 },
    shadowOpacity: 0.38,
    shadowRadius: 30,
    elevation: 10,
  },
  primaryText: {
    color: '#FFFFFF',
    fontSize: 18,
    lineHeight: 23,
    fontWeight: '900',
    textAlign: 'center',
  },
  signInButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingTop: 24,
    paddingBottom: 8,
  },
  signInMuted: {
    color: 'rgba(255, 255, 255, 0.54)',
    fontSize: 14,
    fontWeight: '800',
  },
  signInText: {
    color: '#FFFFFF',
    fontSize: 14,
    fontWeight: '900',
  },
});
