import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import {
  Animated,
  Easing,
  Image,
  ImageBackground,
  NativeScrollEvent,
  NativeSyntheticEvent,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  useWindowDimensions,
  View,
} from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { useRouter } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import Svg, {
  Circle,
  Ellipse,
  Line,
  Path,
  Rect,
  Defs,
  LinearGradient as SvgLinearGradient,
  Stop,
  Text as SvgText,
} from 'react-native-svg';

const shieldLogo = require('../assets/nischint-shield.png');

type Viewport = {
  width: number;
  height: number;
  copyBottom: number;
  bottomBottom: number;
  artBottom: number;
  compact: boolean;
};

const SLIDES = [
  {
    key: 'family',
    cta: 'Get Started',
    title: 'Protect What\nMatters Most',
    subtitle: 'The people you love deserve to feel close, safe, and cared for.',
  },
  {
    key: 'watching',
    cta: 'Continue',
    title: 'Always Watching\nOver Them',
    subtitle: "Every journey matters when it's someone you love.",
  },
  {
    key: 'help',
    cta: 'Create Your Safety Network',
    title: 'Help Arrives\nInstantly',
    subtitle: "Be there for the moments that can't wait.",
  },
];

const FAMILY_PHOTOS = [
  {
    uri: 'https://images.unsplash.com/photo-1742522450616-a2cf0cba1274?w=800&h=1400&fit=crop&auto=format&q=90',
    caption: 'Together, always connected',
  },
  {
    uri: 'https://images.unsplash.com/photo-1659352790654-058e9077a4f4?w=800&h=1400&fit=crop&auto=format&q=90',
    caption: 'Every moment, protected',
  },
  {
    uri: 'https://images.unsplash.com/photo-1655070748916-75871ab03c87?w=800&h=1400&fit=crop&auto=format&q=90',
    caption: 'Connected as one family',
  },
];

const JOURNEY_SCENES = [
  {
    uri: 'https://images.unsplash.com/photo-1677676354332-da185e1efe8c?w=800&h=1400&fit=crop&auto=format&q=92',
    title: 'Journey Safe',
    label: 'Child - Safe Route Active',
    sceneLabel: '01 - Child',
    color: '#00D4FF',
    glowLeft: '39%',
    glowBottom: '22%',
  },
  {
    uri: 'https://images.unsplash.com/photo-1601831155536-39cc6afbd284?w=800&h=1400&fit=crop&auto=format&q=92',
    title: 'Route Normal',
    label: 'Woman - Safe Walk On',
    sceneLabel: '02 - Woman',
    color: '#4ADE80',
    glowLeft: '46%',
    glowBottom: '28%',
  },
  {
    uri: 'https://images.unsplash.com/photo-1764072955216-547f731d176d?w=800&h=1400&fit=crop&auto=format&q=92',
    title: 'Protection Active',
    label: 'Senior - Monitoring On',
    sceneLabel: '03 - Senior',
    color: '#008CFF',
    glowLeft: '42%',
    glowBottom: '20%',
  },
];

const HELP_PHOTO = {
  uri: 'https://images.unsplash.com/photo-1708578120855-7b0936191fee?w=800&h=1400&fit=crop&auto=format&q=90',
};

function useLoop(active: boolean, duration = 5200) {
  const value = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    if (!active) {
      value.stopAnimation();
      value.setValue(0);
      return;
    }

    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(value, {
          toValue: 1,
          duration,
          easing: Easing.inOut(Easing.quad),
          useNativeDriver: true,
        }),
        Animated.timing(value, {
          toValue: 0,
          duration,
          easing: Easing.inOut(Easing.quad),
          useNativeDriver: true,
        }),
      ]),
    );
    loop.start();
    return () => loop.stop();
  }, [active, duration, value]);

  return value;
}

function Brand() {
  return (
    <View style={styles.brand}>
      <Image source={shieldLogo} resizeMode="contain" style={styles.logo} />
      <Text style={styles.brandText}>NISCHINT</Text>
    </View>
  );
}

function SlideFrame({
  children,
  slide,
  activeIndex,
  onRegister,
  onSignIn,
  onDotPress,
  viewport,
}: {
  children: ReactNode;
  slide: typeof SLIDES[number];
  activeIndex: number;
  onRegister: () => void;
  onSignIn: () => void;
  onDotPress: (index: number) => void;
  viewport: Viewport;
}) {
  return (
    <View style={[styles.slide, { width: viewport.width, minHeight: viewport.height }]}>
      {children}
      <Brand />
      <View style={[styles.copy, { bottom: viewport.copyBottom }]}>
        <Text style={[styles.title, viewport.compact && styles.titleCompact]}>{slide.title}</Text>
        <Text style={[styles.subtitle, viewport.compact && styles.subtitleCompact]}>{slide.subtitle}</Text>
      </View>
      <View style={[styles.bottom, { bottom: viewport.bottomBottom }]}>
        <View style={styles.dots}>
          {SLIDES.map((item, index) => (
            <Pressable key={item.key} onPress={() => onDotPress(index)} hitSlop={10}>
              <View style={[styles.dot, index === activeIndex && styles.dotActive]} />
            </Pressable>
          ))}
        </View>
        <Pressable accessibilityLabel="Create account" onPress={onRegister} style={styles.primaryButtonWrap}>
          <LinearGradient colors={['#008CFF', '#00D4FF']} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={styles.primaryButton}>
            <Text style={styles.primaryText}>{slide.cta}</Text>
          </LinearGradient>
        </Pressable>
        <Pressable accessibilityLabel="Sign in" onPress={onSignIn} style={styles.signInButton}>
          <Text style={styles.signInMuted}>Already have an account? </Text>
          <Text style={styles.signInText}>Sign In</Text>
        </Pressable>
      </View>
    </View>
  );
}

function SlideOne({ active, viewport }: { active: boolean; viewport: Viewport }) {
  const [photoIndex, setPhotoIndex] = useState(0);
  const motion = useLoop(active, 5500);
  const photo = FAMILY_PHOTOS[photoIndex];

  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => {
      setPhotoIndex((value) => (value + 1) % FAMILY_PHOTOS.length);
    }, 4000);
    return () => clearInterval(timer);
  }, [active]);

  const scale = motion.interpolate({ inputRange: [0, 1], outputRange: [1.11, 1.01] });
  const translateY = motion.interpolate({ inputRange: [0, 1], outputRange: [-14, 8] });
  const glowScale = motion.interpolate({ inputRange: [0, 1], outputRange: [0.95, 1.12] });
  const glowOpacity = motion.interpolate({ inputRange: [0, 1], outputRange: [0.45, 0.78] });

  return (
    <>
      <Animated.View style={[StyleSheet.absoluteFill, styles.mediaFill, { transform: [{ scale }, { translateY }] }]}>
        <ImageBackground source={{ uri: photo.uri }} resizeMode="cover" style={styles.background} imageStyle={styles.backgroundImage} />
      </Animated.View>
      <LinearGradient
        colors={['rgba(0,0,0,0.14)', 'rgba(0,0,0,0.04)', 'rgba(0,0,0,0.52)', 'rgba(0,0,0,0.98)']}
        locations={[0, 0.34, 0.58, 1]}
        style={StyleSheet.absoluteFill}
      />
      <View style={styles.protectedPill}>
        <View style={styles.statusDot} />
        <Text style={styles.statusText}>Protected</Text>
      </View>
      <Animated.View style={[styles.sunsetGlow, { opacity: glowOpacity, transform: [{ scale: glowScale }] }]} />
      <View style={[styles.photoDots, { bottom: viewport.artBottom + 236 }]}>
        {FAMILY_PHOTOS.map((item, index) => (
          <View key={item.uri} style={[styles.photoDot, index === photoIndex && styles.photoDotActive]} />
        ))}
      </View>
      <Text style={[styles.caption, { bottom: viewport.artBottom + 206 }]}>{photo.caption}</Text>
      <FamilyPortrait screenWidth={viewport.width} screenHeight={viewport.height} bottom={viewport.artBottom} />
    </>
  );
}

function FamilyPortrait({ screenWidth, screenHeight, bottom }: { screenWidth: number; screenHeight: number; bottom: number }) {
  return (
    <Svg width={screenWidth} height={Math.min(screenHeight * 0.47, 420)} viewBox="0 0 390 420" style={[styles.familySvg, { bottom }]}>
      <Ellipse cx="195" cy="380" rx="260" ry="55" fill="rgba(180,100,20,0.18)" />
      <Rect x="120" y="176" width="150" height="120" rx="3" fill="#160904" />
      <Path d="M108 182 L195 130 L282 182 Z" fill="#120702" />
      <Rect x="177" y="260" width="36" height="40" rx="3" fill="#0E0602" />
      <Ellipse cx="55" cy="245" rx="32" ry="38" fill="#1A0E04" />
      <Ellipse cx="335" cy="245" rx="30" ry="36" fill="#1A0E04" />
      <Rect x="0" y="310" width="390" height="110" fill="#100602" />
      <Path d="M155 310 Q195 320 235 310 L245 420 L145 420 Z" fill="#1A0C04" opacity="0.8" />
      {[1, 2, 3].map((ring) => (
        <Ellipse key={ring} cx="197" cy="266" rx={176 + ring * 15} ry={78 + ring * 10} fill="none" stroke="rgba(0,140,255,0.12)" strokeWidth="1.5" />
      ))}
      <Person x={42} y={224} body="#6B7280" label="Grandfather" />
      <Person x={98} y={202} body="#1D4ED8" label="Father" tall />
      <Person x={158} y={216} body="#059669" label="Elder Bro." />
      <Person x={218} y={205} body="#7C3AED" label="Mother" tall />
      <Person x={277} y={249} body="#EF4444" label="Sister" small />
      <Person x={343} y={224} body="#BE185D" label="Grandmother" />
      <Line x1="56" y1="260" x2="68" y2="248" stroke="rgba(220,160,60,0.5)" strokeWidth="3" strokeLinecap="round" />
      <Line x1="126" y1="242" x2="133" y2="254" stroke="rgba(220,160,60,0.5)" strokeWidth="3" strokeLinecap="round" />
      <Line x1="181" y1="252" x2="190" y2="248" stroke="rgba(220,160,60,0.5)" strokeWidth="3" strokeLinecap="round" />
      <Line x1="244" y1="245" x2="256" y2="278" stroke="rgba(220,160,60,0.5)" strokeWidth="3" strokeLinecap="round" />
      <Line x1="298" y1="278" x2="321" y2="260" stroke="rgba(220,160,60,0.5)" strokeWidth="3" strokeLinecap="round" />
    </Svg>
  );
}

function Person({ x, y, body, label, tall, small }: { x: number; y: number; body: string; label: string; tall?: boolean; small?: boolean }) {
  const head = small ? 11 : tall ? 15 : 13;
  const bodyWidth = small ? 24 : tall ? 32 : 24;
  const bodyHeight = small ? 30 : tall ? 38 : 30;
  const bodyTop = y + head;
  const legTop = bodyTop + bodyHeight;
  return (
    <>
      <Circle cx={x} cy={y} r={head} fill="#D4A574" />
      <Rect x={x - bodyWidth / 2} y={bodyTop} width={bodyWidth} height={bodyHeight} rx="6" fill={body} />
      <Line x1={x - bodyWidth / 2} y1={bodyTop + 8} x2={x - bodyWidth / 2 - 12} y2={bodyTop + 26} stroke="#D4A574" strokeWidth="5" strokeLinecap="round" />
      <Line x1={x + bodyWidth / 2} y1={bodyTop + 8} x2={x + bodyWidth / 2 + 12} y2={bodyTop + 24} stroke="#D4A574" strokeWidth="5" strokeLinecap="round" />
      <Line x1={x - 7} y1={legTop} x2={x - 11} y2="298" stroke="#0F172A" strokeWidth="5" strokeLinecap="round" />
      <Line x1={x + 7} y1={legTop} x2={x + 11} y2="298" stroke="#0F172A" strokeWidth="5" strokeLinecap="round" />
      <Ellipse cx={x - 12} cy="300" rx="8" ry="4" fill="#111827" />
      <Ellipse cx={x + 12} cy="300" rx="8" ry="4" fill="#111827" />
      <SvgText x={x} y="316" textAnchor="middle" fill="rgba(255,200,120,0.72)" fontSize="9" fontWeight="600">
        {label}
      </SvgText>
    </>
  );
}

function SlideTwo({ active, viewport }: { active: boolean; viewport: Viewport }) {
  const [sceneIndex, setSceneIndex] = useState(0);
  const [showCard, setShowCard] = useState(false);
  const motion = useLoop(active, 5500);
  const scene = JOURNEY_SCENES[sceneIndex];

  useEffect(() => {
    if (!active) return;
    setShowCard(false);
    const show = setTimeout(() => setShowCard(true), 900);
    const hide = setTimeout(() => setShowCard(false), 2900);
    const next = setInterval(() => {
      setSceneIndex((value) => (value + 1) % JOURNEY_SCENES.length);
      setShowCard(false);
      setTimeout(() => setShowCard(true), 900);
      setTimeout(() => setShowCard(false), 2900);
    }, 4200);
    return () => {
      clearTimeout(show);
      clearTimeout(hide);
      clearInterval(next);
    };
  }, [active]);

  const scale = motion.interpolate({ inputRange: [0, 1], outputRange: [1.12, 1.02] });
  const translateX = motion.interpolate({ inputRange: [0, 1], outputRange: [8, -12] });
  const ringScale = motion.interpolate({ inputRange: [0, 1], outputRange: [0.85, 1.12] });
  const ringOpacity = motion.interpolate({ inputRange: [0, 1], outputRange: [0.8, 0.38] });

  return (
    <>
      <Animated.View style={[StyleSheet.absoluteFill, styles.mediaFill, { transform: [{ scale }, { translateX }] }]}>
        <ImageBackground source={{ uri: scene.uri }} resizeMode="cover" style={styles.background} imageStyle={styles.backgroundImage} />
      </Animated.View>
      <LinearGradient
        colors={['rgba(4,6,12,0.45)', 'rgba(4,6,12,0.02)', 'rgba(4,6,12,0.42)', 'rgba(4,6,12,1)']}
        locations={[0, 0.36, 0.62, 1]}
        style={StyleSheet.absoluteFill}
      />
      <Animated.View
        style={[
          styles.routeGlow,
          {
            left: scene.glowLeft as any,
            bottom: scene.glowBottom as any,
            borderColor: `${scene.color}88`,
            opacity: ringOpacity,
            transform: [{ scale: ringScale }],
          },
        ]}
      />
      <ParticleField />
      {showCard ? <StatusCard title={scene.title} label={scene.label} bottom={viewport.copyBottom + 24} /> : null}
      <Text style={[styles.sceneLabel, { bottom: viewport.copyBottom - 14 }]}>{scene.sceneLabel}</Text>
      <View style={[styles.sceneProgress, { bottom: viewport.copyBottom - 22 }]}>
        <Animated.View style={[styles.sceneProgressFill, { backgroundColor: scene.color }]} />
      </View>
    </>
  );
}

function ParticleField() {
  const particles = useMemo(
    () => [
      ['18%', '35%', '#00D4FF'],
      ['72%', '28%', '#4ADE80'],
      ['55%', '18%', '#FFFFFF'],
      ['28%', '52%', '#00D4FF'],
      ['82%', '45%', '#4ADE80'],
      ['65%', '60%', '#FFFFFF'],
    ],
    [],
  );

  return (
    <>
      {particles.map(([left, top, color], index) => (
        <View key={`${left}-${top}`} style={[styles.particle, { left: left as any, top: top as any, backgroundColor: color, opacity: index % 2 ? 0.42 : 0.68 }]} />
      ))}
    </>
  );
}

function StatusCard({ title, label, bottom }: { title: string; label: string; bottom: number }) {
  return (
    <View style={[styles.statusCard, { bottom }]}>
      <View style={styles.statusDotPulse}>
        <View style={styles.statusDot} />
      </View>
      <View>
        <Text style={styles.statusCardTitle}>✓ {title}</Text>
        <Text style={styles.statusCardLabel}>{label}</Text>
      </View>
    </View>
  );
}

function SlideThree({ active, viewport }: { active: boolean; viewport: Viewport }) {
  const [phase, setPhase] = useState(0);
  const motion = useLoop(active, 7000);

  useEffect(() => {
    if (!active) {
      setPhase(0);
      return;
    }
    const timings = [2200, 3400, 4800, 6400, 9200];
    const timers = timings.map((time, index) => setTimeout(() => setPhase(index + 1), time));
    const interval = setInterval(() => {
      setPhase(0);
      timings.forEach((time, index) => setTimeout(() => setPhase(index + 1), time));
    }, 12800);
    return () => {
      timers.forEach(clearTimeout);
      clearInterval(interval);
    };
  }, [active]);

  const scale = motion.interpolate({ inputRange: [0, 1], outputRange: [1.06, 1.0] });
  const pulseScale = motion.interpolate({ inputRange: [0, 1], outputRange: [0.65, 1.15] });
  const pulseOpacity = motion.interpolate({ inputRange: [0, 1], outputRange: [0.8, 0.08] });

  return (
    <>
      <Animated.View style={[StyleSheet.absoluteFill, styles.mediaFill, { transform: [{ scale }] }]}>
        <ImageBackground source={HELP_PHOTO} resizeMode="cover" style={styles.background} imageStyle={styles.backgroundImage} />
      </Animated.View>
      <LinearGradient
        colors={['rgba(5,8,15,0.28)', 'rgba(5,8,15,0.02)', 'rgba(5,8,15,0.48)', 'rgba(5,8,15,1)']}
        locations={[0, 0.35, 0.6, 1]}
        style={StyleSheet.absoluteFill}
      />
      <View style={[styles.moodOverlay, phase <= 2 ? styles.moodConcern : styles.moodProtected]} />
      {phase >= 2 ? (
        <View style={styles.sosSignal}>
          <Animated.View style={[styles.sosPulseRing, { opacity: pulseOpacity, transform: [{ scale: pulseScale }] }]} />
          <View style={styles.sosPill}>
            <View style={styles.cyanDot} />
            <Text style={styles.sosPillText}>SOS</Text>
          </View>
        </View>
      ) : null}
      {phase >= 3 ? <PulseLine screenWidth={viewport.width} screenHeight={viewport.height} /> : null}
      {phase >= 4 ? (
        <View style={styles.guardianStack}>
          <GuardianNotice title="Primary Guardian notified" icon="🛡" />
          <GuardianNotice title="Co-Guardian notified" icon="👤" />
        </View>
      ) : null}
      {phase >= 5 ? (
        <View style={styles.helpPill}>
          <View style={styles.statusDot} />
          <Text style={styles.helpPillText}>Help is on the way</Text>
        </View>
      ) : null}
    </>
  );
}

function PulseLine({ screenWidth, screenHeight }: { screenWidth: number; screenHeight: number }) {
  return (
    <Svg width={screenWidth} height={screenHeight} style={StyleSheet.absoluteFill}>
      <Defs>
        <SvgLinearGradient id="pulseGrad" x1="0" y1="1" x2="0" y2="0">
          <Stop offset="0%" stopColor="#4ADE80" stopOpacity="0.9" />
          <Stop offset="50%" stopColor="#00D4FF" stopOpacity="0.75" />
          <Stop offset="100%" stopColor="#008CFF" stopOpacity="0.3" />
        </SvgLinearGradient>
      </Defs>
      <Line x1={screenWidth / 2} y1={screenHeight * 0.68} x2={screenWidth / 2} y2={screenHeight * 0.12} stroke="url(#pulseGrad)" strokeWidth="1.5" strokeDasharray="6 4" strokeLinecap="round" />
      <Circle cx={screenWidth / 2} cy={screenHeight * 0.15} r="4" fill="#00D4FF" />
    </Svg>
  );
}

function GuardianNotice({ title, icon }: { title: string; icon: string }) {
  return (
    <View style={styles.guardianCard}>
      <View style={styles.guardianIcon}>
        <Text style={styles.guardianIconText}>{icon}</Text>
      </View>
      <View style={styles.guardianCopy}>
        <Text style={styles.guardianTitle}>{title}</Text>
        <Text style={styles.guardianText}>Responding now</Text>
      </View>
      <View style={styles.guardianDot} />
    </View>
  );
}

export default function FigmaOnboarding() {
  const router = useRouter();
  const { width, height } = useWindowDimensions();
  const scrollRef = useRef<ScrollView>(null);
  const [activeIndex, setActiveIndex] = useState(0);
  const viewport = useMemo<Viewport>(() => {
    const compact = height < 720;
    return {
      width,
      height,
      compact,
      bottomBottom: Math.max(22, Math.min(40, height * 0.043)),
      copyBottom: Math.max(compact ? 166 : 190, Math.min(230, height * 0.25)),
      artBottom: Math.max(92, Math.min(136, height * 0.14)),
    };
  }, [height, width]);

  const goRegister = () => router.replace('/(auth)/register');
  const goSignIn = () => router.replace('/(auth)/login');
  const goTo = (index: number) => {
    scrollRef.current?.scrollTo({ x: index * width, animated: true });
    setActiveIndex(index);
  };
  const onScrollEnd = (event: NativeSyntheticEvent<NativeScrollEvent>) => {
    const nextIndex = Math.round(event.nativeEvent.contentOffset.x / width);
    setActiveIndex(Math.max(0, Math.min(SLIDES.length - 1, nextIndex)));
  };

  return (
    <View style={styles.screen}>
      <StatusBar style="light" />
      <ScrollView
        ref={scrollRef}
        horizontal
        pagingEnabled
        bounces={false}
        style={styles.pager}
        contentContainerStyle={{ minHeight: height }}
        showsHorizontalScrollIndicator={false}
        onMomentumScrollEnd={onScrollEnd}
        scrollEventThrottle={16}
      >
        <SlideFrame slide={SLIDES[0]} activeIndex={activeIndex} onRegister={goRegister} onSignIn={goSignIn} onDotPress={goTo} viewport={viewport}>
          <SlideOne active={activeIndex === 0} viewport={viewport} />
        </SlideFrame>
        <SlideFrame slide={SLIDES[1]} activeIndex={activeIndex} onRegister={goRegister} onSignIn={goSignIn} onDotPress={goTo} viewport={viewport}>
          <SlideTwo active={activeIndex === 1} viewport={viewport} />
        </SlideFrame>
        <SlideFrame slide={SLIDES[2]} activeIndex={activeIndex} onRegister={goRegister} onSignIn={goSignIn} onDotPress={goTo} viewport={viewport}>
          <SlideThree active={activeIndex === 2} viewport={viewport} />
        </SlideFrame>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: '#04080E' },
  pager: { flex: 1 },
  slide: { flex: 1, backgroundColor: '#04080E', overflow: 'hidden' },
  mediaFill: { overflow: 'hidden', backgroundColor: '#04080E' },
  background: { flex: 1, width: '100%', height: '100%' },
  backgroundImage: { width: '100%', height: '100%' },
  brand: {
    position: 'absolute',
    top: 54,
    alignSelf: 'center',
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    zIndex: 30,
  },
  logo: { width: 32, height: 32 },
  brandText: {
    color: '#FFFFFF',
    fontSize: 15,
    fontWeight: '900',
    letterSpacing: 3,
    textShadowColor: 'rgba(0,0,0,0.7)',
    textShadowOffset: { width: 0, height: 1 },
    textShadowRadius: 10,
  },
  copy: { position: 'absolute', left: 24, right: 24, zIndex: 20 },
  title: {
    color: '#FFFFFF',
    fontSize: 32,
    lineHeight: 36,
    fontWeight: '900',
    textShadowColor: 'rgba(0,0,0,0.65)',
    textShadowOffset: { width: 0, height: 2 },
    textShadowRadius: 18,
  },
  titleCompact: { fontSize: 28, lineHeight: 32 },
  subtitle: { color: 'rgba(255,255,255,0.62)', fontSize: 13, lineHeight: 20, fontWeight: '700', marginTop: 12, maxWidth: 310 },
  subtitleCompact: { marginTop: 9, lineHeight: 18 },
  bottom: { position: 'absolute', left: 24, right: 24, zIndex: 30 },
  dots: { flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 20 },
  dot: { width: 7, height: 7, borderRadius: 4, backgroundColor: 'rgba(255,255,255,0.42)' },
  dotActive: { width: 28, backgroundColor: '#00D4FF' },
  primaryButtonWrap: { width: '100%', borderRadius: 18, overflow: 'hidden', shadowColor: '#008CFF', shadowOffset: { width: 0, height: 8 }, shadowOpacity: 0.42, shadowRadius: 24, elevation: 8 },
  primaryButton: { height: 54, alignItems: 'center', justifyContent: 'center', borderRadius: 18 },
  primaryText: { color: '#FFFFFF', fontSize: 16, fontWeight: '900' },
  signInButton: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', paddingTop: 18, paddingBottom: 4 },
  signInMuted: { color: 'rgba(255,255,255,0.42)', fontSize: 13, fontWeight: '800' },
  signInText: { color: 'rgba(255,255,255,0.78)', fontSize: 13, fontWeight: '900' },
  protectedPill: {
    position: 'absolute',
    top: 88,
    right: 20,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingHorizontal: 13,
    paddingVertical: 8,
    borderRadius: 18,
    backgroundColor: 'rgba(0,140,255,0.18)',
    borderWidth: 1,
    borderColor: 'rgba(0,140,255,0.35)',
    zIndex: 8,
  },
  statusDot: { width: 8, height: 8, borderRadius: 4, backgroundColor: '#4ADE80' },
  cyanDot: { width: 7, height: 7, borderRadius: 4, backgroundColor: '#00D4FF' },
  statusText: { color: '#FFFFFF', fontSize: 12, fontWeight: '900' },
  sunsetGlow: {
    position: 'absolute',
    width: 360,
    height: 300,
    borderRadius: 180,
    bottom: '25%',
    alignSelf: 'center',
    backgroundColor: 'rgba(220,140,40,0.22)',
  },
  photoDots: { position: 'absolute', alignSelf: 'center', flexDirection: 'row', alignItems: 'center', gap: 6, zIndex: 15 },
  photoDot: { width: 5, height: 5, borderRadius: 3, backgroundColor: 'rgba(255,255,255,0.4)' },
  photoDotActive: { width: 18, backgroundColor: '#FFFFFF' },
  caption: { position: 'absolute', left: 24, right: 24, color: 'rgba(255,255,255,0.62)', fontSize: 13, fontWeight: '800', zIndex: 15 },
  familySvg: { position: 'absolute', left: 0 },
  routeGlow: {
    position: 'absolute',
    width: 112,
    height: 112,
    marginLeft: -56,
    marginBottom: -56,
    borderRadius: 56,
    borderWidth: 1.5,
    backgroundColor: 'rgba(0,212,255,0.08)',
  },
  particle: { position: 'absolute', width: 4, height: 4, borderRadius: 2 },
  statusCard: {
    position: 'absolute',
    left: 20,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    paddingHorizontal: 15,
    paddingVertical: 11,
    borderRadius: 18,
    backgroundColor: 'rgba(255,255,255,0.12)',
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.14)',
    zIndex: 10,
  },
  statusDotPulse: { width: 13, height: 13, borderRadius: 7, alignItems: 'center', justifyContent: 'center' },
  statusCardTitle: { color: '#FFFFFF', fontSize: 14, fontWeight: '900' },
  statusCardLabel: { color: 'rgba(255,255,255,0.52)', fontSize: 12, fontWeight: '700', marginTop: 2 },
  sceneLabel: { position: 'absolute', left: 20, bottom: 196, color: 'rgba(255,255,255,0.34)', fontSize: 10, fontWeight: '900', letterSpacing: 2, textTransform: 'uppercase' },
  sceneProgress: { position: 'absolute', left: 20, bottom: 188, width: 66, height: 2, borderRadius: 1, backgroundColor: 'rgba(255,255,255,0.12)', overflow: 'hidden' },
  sceneProgressFill: { width: '70%', height: 2 },
  moodOverlay: { ...StyleSheet.absoluteFillObject },
  moodConcern: { backgroundColor: 'rgba(30,8,20,0.16)' },
  moodProtected: { backgroundColor: 'rgba(0,140,120,0.13)' },
  sosSignal: { position: 'absolute', bottom: '32%', alignSelf: 'center', alignItems: 'center', justifyContent: 'center' },
  sosPulseRing: { position: 'absolute', width: 120, height: 120, borderRadius: 60, borderWidth: 1, borderColor: 'rgba(0,180,240,0.45)' },
  sosPill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 7,
    paddingHorizontal: 13,
    paddingVertical: 8,
    borderRadius: 18,
    backgroundColor: 'rgba(0,160,220,0.15)',
    borderWidth: 1,
    borderColor: 'rgba(0,180,240,0.35)',
  },
  sosPillText: { color: '#FFFFFF', fontSize: 12, fontWeight: '900', letterSpacing: 1 },
  guardianStack: { position: 'absolute', top: '14%', left: 20, right: 20, gap: 10, zIndex: 16 },
  guardianCard: {
    minHeight: 58,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingHorizontal: 14,
    borderRadius: 17,
    backgroundColor: 'rgba(255,255,255,0.09)',
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.13)',
  },
  guardianIcon: { width: 34, height: 34, borderRadius: 17, alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(0,140,255,0.18)' },
  guardianIconText: { color: '#FFFFFF', fontSize: 17, fontWeight: '900' },
  guardianCopy: { flex: 1 },
  guardianTitle: { color: '#FFFFFF', fontSize: 14, fontWeight: '900' },
  guardianText: { color: 'rgba(255,255,255,0.44)', fontSize: 12, fontWeight: '700', marginTop: 2 },
  guardianDot: { width: 8, height: 8, borderRadius: 4, backgroundColor: '#4ADE80' },
  helpPill: {
    position: 'absolute',
    left: 20,
    bottom: '29%',
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    paddingHorizontal: 15,
    paddingVertical: 11,
    borderRadius: 22,
    backgroundColor: 'rgba(0,180,220,0.14)',
    borderWidth: 1,
    borderColor: 'rgba(0,212,255,0.3)',
    zIndex: 15,
  },
  helpPillText: { color: '#FFFFFF', fontSize: 14, fontWeight: '900' },
});
