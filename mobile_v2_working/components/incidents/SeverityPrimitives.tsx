// NISCH-007 Part B — leaf component: severity dot + state badge primitives.
//
// Pure, allocation-free leaf views the row + sheet share. Keeping the
// color tables here means the screen file never has to know about them.
import React from 'react';
import { View, Text, StyleSheet } from 'react-native';

export const SEVERITY_COLORS: Record<string, string> = {
  critical: '#EF4444',
  high:     '#F59E0B',
  medium:   '#EAB308',
  low:      '#94A3B8',
};

// State labels are returned by the API — these are ONLY for badge styling.
// We never render the state name itself; the API ships the user-facing label.
export const BADGE_COLORS: Record<string, { bg: string; text: string }> = {
  detected:     { bg: '#FEF2F2', text: '#DC2626' },
  validating:   { bg: '#FFF7ED', text: '#C2410C' },
  escalated:    { bg: '#FFFBEB', text: '#B45309' },
  acknowledged: { bg: '#EFF6FF', text: '#1D4ED8' },
  resolved:     { bg: '#F0FDF4', text: '#15803D' },
};

// Dark-theme overrides (the app's bgCard is dark slate; the original light
// pastels would disappear). We pick deeper backgrounds with the same hue
// family so the badge identity is preserved across themes.
const DARK_BADGE_BG: Record<string, string> = {
  detected:     '#3F1D1D',
  validating:   '#3F2515',
  escalated:    '#3F2F0E',
  acknowledged: '#1E2C4D',
  resolved:     '#102A1B',
};

export function SeverityDot({ severity, size = 10 }: { severity: string; size?: number }) {
  const color = SEVERITY_COLORS[severity?.toLowerCase()] || SEVERITY_COLORS.low;
  return (
    <View
      testID={`severity-dot-${severity}`}
      style={{
        width: size, height: size, borderRadius: size / 2,
        backgroundColor: color,
      }}
    />
  );
}

export function StateBadge({ state, label }: { state: string; label: string }) {
  // We render `label` (the user-facing copy from the API), but key styling
  // off `state` (the enum value) — that's the only place the raw state
  // name lives in the UI tree, and it's never displayed.
  const key = (state || '').toLowerCase();
  const palette = BADGE_COLORS[key] || BADGE_COLORS.detected;
  const darkBg = DARK_BADGE_BG[key] || palette.bg;
  return (
    <View
      testID={`state-badge-${state}`}
      style={[styles.badge, { backgroundColor: darkBg, borderColor: palette.text }]}
    >
      <Text style={[styles.badgeText, { color: palette.text }]}>
        {label}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  badge: {
    alignSelf: 'flex-start',
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 6,
    borderWidth: 1,
  },
  badgeText: {
    fontSize: 11,
    fontWeight: '700',
    letterSpacing: 0.3,
  },
});
