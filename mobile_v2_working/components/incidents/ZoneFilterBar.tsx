// NISCH-007 Part B — Zone filter chip bar.
//
// Horizontal scroll of pill chips. Active chip = teal fill. "All" maps
// to a `null` zone param (omitted from the request entirely).
import React from 'react';
import {
  ScrollView, TouchableOpacity, Text, View, StyleSheet,
} from 'react-native';
import { colors } from '@/theme';

export type ZoneKey = 'all' | 'home' | 'school' | 'office' | 'route';

const CHIPS: { key: ZoneKey; label: string }[] = [
  { key: 'all',    label: 'All'    },
  { key: 'home',   label: 'Home'   },
  { key: 'school', label: 'School' },
  { key: 'office', label: 'Office' },
  { key: 'route',  label: 'Route'  },
];

interface Props {
  active: ZoneKey;
  onChange: (z: ZoneKey) => void;
}

export function ZoneFilterBar({ active, onChange }: Props) {
  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      contentContainerStyle={styles.row}
      testID="zone-filter-bar"
    >
      {CHIPS.map((c) => {
        const isActive = c.key === active;
        return (
          <TouchableOpacity
            key={c.key}
            testID={`zone-chip-${c.key}`}
            accessibilityRole="button"
            accessibilityState={{ selected: isActive }}
            activeOpacity={0.85}
            onPress={() => onChange(c.key)}
            style={[styles.chip, isActive ? styles.chipActive : styles.chipInactive]}
          >
            <Text style={[styles.chipText, isActive && styles.chipTextActive]}>
              {c.label}
            </Text>
          </TouchableOpacity>
        );
      })}
      <View style={{ width: 8 }} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    paddingHorizontal: 12,
    paddingVertical: 8,
    gap: 8,
  },
  chip: {
    minHeight: 36,
    paddingHorizontal: 16,
    borderRadius: 18,
    borderWidth: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  chipActive: {
    backgroundColor: colors.primary,
    borderColor: colors.primary,
  },
  chipInactive: {
    backgroundColor: 'transparent',
    borderColor: colors.border,
  },
  chipText: {
    fontSize: 13,
    fontWeight: '600',
    color: colors.textSecondary,
  },
  chipTextActive: {
    color: colors.white,
  },
});
