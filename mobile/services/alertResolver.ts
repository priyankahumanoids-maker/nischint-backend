// Unified Alert Resolver — ONE source of truth for guardian alert state
// Priority: EMERGENCY > ESCALATION > VOICE_DISTRESS > HELP > CHECKIN > SAFE

export type AlertPriority = 'EMERGENCY' | 'ESCALATION' | 'VOICE_DISTRESS' | 'HELP' | 'CHECKIN' | 'SAFE';

export interface UnifiedAlert {
  id: string;
  alert_type: string;
  severity: string;
  message: string;
  user_name?: string;
  child_id?: string;
  child_name?: string;
  created_at: string;
  source: 'api' | 'sse' | 'push';
  acknowledged?: boolean;
}

export interface AlertAction {
  label: string;
  icon: string;
  screen: string; // navigation target
}

export interface AlertState {
  type: AlertPriority;
  alert: UnifiedAlert | null;
  allActive: UnifiedAlert[];
  action: AlertAction | null;
}

// Map raw alert_type strings to priority enum
const TYPE_MAP: Record<string, AlertPriority> = {
  'emergency_triggered': 'EMERGENCY',
  'auto_escalated': 'ESCALATION',
  'voice_distress': 'VOICE_DISTRESS',
  'help_requested': 'HELP',
  'check_in_pending': 'CHECKIN',
  'checkin_pending': 'CHECKIN',
  'check_in_expired': 'CHECKIN',
};

const PRIORITY_ORDER: AlertPriority[] = [
  'EMERGENCY',
  'ESCALATION',
  'VOICE_DISTRESS',
  'HELP',
  'CHECKIN',
];

// Action binding per alert type — what happens when user taps the banner
const ACTION_MAP: Record<AlertPriority, AlertAction> = {
  'EMERGENCY': { label: 'Open Live Map', icon: 'map', screen: 'live-map' },
  'ESCALATION': { label: 'Call Now', icon: 'call', screen: 'call' },
  'VOICE_DISTRESS': { label: 'View Alert', icon: 'mic', screen: 'live-map' },
  'HELP': { label: 'Call / Chat', icon: 'chatbubble-ellipses', screen: 'call' },
  'CHECKIN': { label: 'Respond', icon: 'notifications', screen: 'checkin' },
  'SAFE': { label: '', icon: '', screen: '' },
};

const ALERT_TTL_MS = 2 * 60 * 1000; // 2 minutes auto-expiry

// Critical alert types that NEVER auto-expire via TTL
// Only removed by: user dismiss OR backend resolved event
const CRITICAL_LOCK_TYPES = new Set<AlertPriority>(['EMERGENCY', 'ESCALATION']);

/**
 * Resolve the single highest-priority alert state from all sources.
 * Deduplicates by ID, filters expired (>2 min) EXCEPT critical locks, sorts by priority+recency.
 */
export function resolveAlertState(alerts: UnifiedAlert[]): AlertState {
  if (!alerts || alerts.length === 0) {
    return { type: 'SAFE', alert: null, allActive: [], action: null };
  }

  const now = Date.now();

  // Deduplicate by ID (keep latest)
  const seen = new Map<string, UnifiedAlert>();
  for (const a of alerts) {
    if (!seen.has(a.id)) {
      seen.set(a.id, a);
    }
  }

  // Filter: must be active type + not expired (TTL) — CRITICAL LOCK: never expire EMERGENCY/ESCALATION
  const active = Array.from(seen.values()).filter((a) => {
    const priority = TYPE_MAP[a.alert_type];
    if (!priority) return false;
    // Critical lock — NEVER auto-expire
    if (CRITICAL_LOCK_TYPES.has(priority)) return true;
    const age = now - new Date(a.created_at).getTime();
    return age < ALERT_TTL_MS;
  });

  if (active.length === 0) {
    return { type: 'SAFE', alert: null, allActive: [], action: null };
  }

  // Sort by priority then recency
  active.sort((a, b) => {
    const pa = PRIORITY_ORDER.indexOf(TYPE_MAP[a.alert_type] || 'CHECKIN');
    const pb = PRIORITY_ORDER.indexOf(TYPE_MAP[b.alert_type] || 'CHECKIN');
    if (pa !== pb) return pa - pb;
    return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
  });

  const top = active[0];
  const priority = TYPE_MAP[top.alert_type] || 'SAFE';
  return {
    type: priority,
    alert: top,
    allActive: active,
    action: ACTION_MAP[priority] || null,
  };
}

/**
 * Merge multiple alert sources into one array.
 * Deduplicates by ID — SSE/push alerts override API alerts (fresher data).
 */
export function mergeAlertSources(
  apiAlerts: any[],
  sseAlerts: UnifiedAlert[],
  pushAlerts: UnifiedAlert[] = [],
): UnifiedAlert[] {
  const merged = new Map<string, UnifiedAlert>();

  // API alerts first (lowest precedence)
  for (const a of apiAlerts) {
    const ua: UnifiedAlert = {
      id: a.id || `api-${Date.now()}`,
      alert_type: a.alert_type || a.type || 'unknown',
      severity: a.severity || 'medium',
      message: a.message || '',
      user_name: a.user_name,
      child_id: a.child_id,
      child_name: a.child_name || a.user_name,
      created_at: a.created_at || new Date().toISOString(),
      source: 'api',
    };
    merged.set(ua.id, ua);
  }

  // SSE alerts override (higher precedence)
  for (const a of sseAlerts) {
    merged.set(a.id, a);
  }

  // Push alerts override (highest precedence)
  for (const a of pushAlerts) {
    merged.set(a.id, a);
  }

  return Array.from(merged.values());
}
