// NISCH-007 Part B — Feed list view.
//
// FlatList of IncidentFeedRow with pull-to-refresh. Empty state
// renders calmly per spec — no alarm iconography.
import React from 'react';
import {
  FlatList, View, Text, RefreshControl, StyleSheet,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { colors } from '@/theme';
import { IncidentFeedRow, FeedIncident } from './IncidentFeedRow';

interface Props {
  incidents: FeedIncident[];
  refreshing: boolean;
  onRefresh: () => void;
  onRowPress: (id: string) => void;
}

export function IncidentFeedList({
  incidents, refreshing, onRefresh, onRowPress,
}: Props) {
  return (
    <FlatList
      testID="incident-feed-list"
      data={incidents}
      keyExtractor={(i) => i.id}
      renderItem={({ item }) => (
        <IncidentFeedRow incident={item} onPress={onRowPress} />
      )}
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          onRefresh={onRefresh}
          tintColor={colors.primary}
        />
      }
      ListEmptyComponent={!refreshing ? <EmptyState /> : null}
      contentContainerStyle={incidents.length === 0 ? styles.emptyContainer : undefined}
    />
  );
}

function EmptyState() {
  return (
    <View style={styles.empty} testID="empty-state">
      <View style={styles.emptyIcon}>
        <Ionicons name="ellipse-outline" size={32} color={colors.primary} />
      </View>
      <Text style={styles.emptyTitle}>No incidents near you right now</Text>
      <Text style={styles.emptySubtitle}>Pull down to refresh</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  emptyContainer: {
    flexGrow: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  empty: {
    alignItems: 'center',
    paddingHorizontal: 32,
    gap: 8,
  },
  emptyIcon: {
    width: 56, height: 56,
    borderRadius: 28,
    backgroundColor: 'rgba(14, 165, 233, 0.08)',
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 8,
  },
  emptyTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: colors.textPrimary,
  },
  emptySubtitle: {
    fontSize: 13,
    color: colors.textMuted,
  },
});
