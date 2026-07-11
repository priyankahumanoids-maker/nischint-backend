// NISCHINT Design System
import { Dimensions } from 'react-native';

const { width, height } = Dimensions.get('window');

export const colors = {
  // Core
  bg: '#0B0F1A',
  bgCard: '#111827',
  bgElevated: '#1A2035',
  bgInput: '#1E293B',
  border: '#1E293B',
  borderActive: '#0EA5E9',

  // Brand
  primary: '#0EA5E9',
  primaryDark: '#0284C7',
  primaryLight: '#38BDF8',

  // Safety spectrum
  critical: '#EF4444',
  high: '#F97316',
  moderate: '#EAB308',
  safe: '#22C55E',
  verySafe: '#10B981',

  // Text
  textPrimary: '#F1F5F9',
  textSecondary: '#94A3B8',
  textMuted: '#64748B',
  textInverse: '#0B0F1A',

  // Accent
  accent: '#8B5CF6',
  accentPink: '#EC4899',
  white: '#FFFFFF',
  black: '#000000',
  transparent: 'transparent',

  // Status
  success: '#22C55E',
  warning: '#EAB308',
  error: '#EF4444',
  info: '#0EA5E9',
};

export const spacing = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 20,
  '2xl': 24,
  '3xl': 32,
  '4xl': 40,
  '5xl': 48,
};

export const fontSize = {
  xs: 11,
  sm: 13,
  md: 15,
  lg: 17,
  xl: 20,
  '2xl': 24,
  '3xl': 30,
  '4xl': 36,
};

export const radius = {
  sm: 6,
  md: 10,
  lg: 14,
  xl: 20,
  full: 999,
};

export const screen = { width, height };

export const shadows = {
  sm: {
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.2,
    shadowRadius: 2,
    elevation: 2,
  },
  md: {
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.3,
    shadowRadius: 4,
    elevation: 4,
  },
  lg: {
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.4,
    shadowRadius: 8,
    elevation: 8,
  },
};

// Safety score category colors
export const scoreColor = (score: number): string => {
  if (score >= 8) return colors.verySafe;
  if (score >= 6) return colors.safe;
  if (score >= 4) return colors.moderate;
  if (score >= 2) return colors.high;
  return colors.critical;
};

export const scoreLabel = (score: number): string => {
  if (score >= 8) return 'Very Safe';
  if (score >= 6) return 'Safe';
  if (score >= 4) return 'Moderate';
  if (score >= 2) return 'High Risk';
  return 'Critical';
};

export const riskColor = (level: string): string => {
  switch (level) {
    case 'critical': return colors.critical;
    case 'high': return colors.high;
    case 'moderate': return colors.moderate;
    case 'safe': return colors.safe;
    default: return colors.textMuted;
  }
};
