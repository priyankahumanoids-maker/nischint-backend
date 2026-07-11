// NISCH-007 Part B — Animated map marker.
//
// Renders the severity-colored dot. For escalated state, wraps it in
// an Animated.loop pulsing ring (scale 1→1.3, opacity 1→0). All other
// states are static.
//
// Defined as a separate component so React can stably mount/unmount
// the Animated machinery — putting Animated.Value inline in IncidentMapView
// would re-create it every render and never play.
import React, { useEffect, useRef } from 'react';
import { Animated, View, StyleSheet } from 'react-native';
import { SEVERITY_COLORS } from './SeverityPrimitives';

interface Props {
  severity: string;
  state:    string;
}

export function PulsingMarker({ severity, state }: Props) {
  const color = SEVERITY_COLORS[(severity || '').toLowerCase()] || SEVERITY_COLORS.low;
  const isEscalated = (state || '').toLowerCase() === 'escalated';
  const scale   = useRef(new Animated.Value(1)).current;
  const opacity = useRef(new Animated.Value(1)).current;

  useEffect(() => {
    if (!isEscalated) return;
    const loop = Animated.loop(
      Animated.parallel([
        Animated.sequence([
          Animated.timing(scale, {
            toValue: 1.3, duration: 1500, useNativeDriver: true,
          }),
          Animated.timing(scale, {
            toValue: 1, duration: 0, useNativeDriver: true,
          }),
        ]),
        Animated.sequence([
          Animated.timing(opacity, {
            toValue: 0, duration: 1500, useNativeDriver: true,
          }),
          Animated.timing(opacity, {
            toValue: 1, duration: 0, useNativeDriver: true,
          }),
        ]),
      ])
    );
    loop.start();
    return () => loop.stop();
  }, [isEscalated, scale, opacity]);

  return (
    <View style={styles.wrapper}>
      {isEscalated && (
        <Animated.View
          style={[
            styles.ring,
            {
              backgroundColor: color,
              transform: [{ scale }],
              opacity,
            },
          ]}
        />
      )}
      <View style={[styles.dot, { backgroundColor: color }]} />
    </View>
  );
}

const styles = StyleSheet.create({
  wrapper: {
    width: 28,
    height: 28,
    alignItems: 'center',
    justifyContent: 'center',
  },
  ring: {
    position: 'absolute',
    width: 28,
    height: 28,
    borderRadius: 14,
  },
  dot: {
    width: 14,
    height: 14,
    borderRadius: 7,
    borderWidth: 2,
    borderColor: '#FFFFFF',
  },
});
