// Offline Event Queue — backed by AsyncStorage
// Events are flushed to backend via journeyService when network is available.
// Queue survives app restarts.
import AsyncStorage from '@react-native-async-storage/async-storage';

const KEY = 'nischint.journey.offline_queue.v1';
const MAX_RETRIES = 5;
const MAX_QUEUE_SIZE = 500;

export interface QueuedEvent {
  id: string;                // uuid or ts-based
  type: string;              // 'location_update' | 'voice_distress' | 'state_change' | ...
  payload: Record<string, any>;
  retry_count: number;
  created_at: number;
  last_attempt_at?: number;
}

let _memoryCache: QueuedEvent[] | null = null;

async function load(): Promise<QueuedEvent[]> {
  if (_memoryCache) return _memoryCache;
  try {
    const raw = await AsyncStorage.getItem(KEY);
    _memoryCache = raw ? (JSON.parse(raw) as QueuedEvent[]) : [];
  } catch (e) {
    console.warn('[OFFLINE_Q] load failed', e);
    _memoryCache = [];
  }
  return _memoryCache!;
}

async function save(items: QueuedEvent[]): Promise<void> {
  _memoryCache = items;
  try {
    await AsyncStorage.setItem(KEY, JSON.stringify(items));
  } catch (e) {
    console.warn('[OFFLINE_Q] save failed', e);
  }
}

export async function enqueue(type: string, payload: Record<string, any>): Promise<void> {
  const items = await load();
  items.push({
    id: `${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
    type,
    payload,
    retry_count: 0,
    created_at: Date.now(),
  });
  // Cap queue size — drop oldest
  while (items.length > MAX_QUEUE_SIZE) items.shift();
  await save(items);
}

export async function peek(max: number = 10): Promise<QueuedEvent[]> {
  const items = await load();
  // Return oldest-first, up to `max` and within retry budget
  return items.filter((i) => i.retry_count < MAX_RETRIES).slice(0, max);
}

export async function size(): Promise<number> {
  return (await load()).length;
}

export async function markSuccess(ids: string[]): Promise<void> {
  if (!ids.length) return;
  const set = new Set(ids);
  const items = (await load()).filter((i) => !set.has(i.id));
  await save(items);
}

export async function markFailure(ids: string[]): Promise<void> {
  if (!ids.length) return;
  const set = new Set(ids);
  const now = Date.now();
  const items = await load();
  for (const item of items) {
    if (set.has(item.id)) {
      item.retry_count += 1;
      item.last_attempt_at = now;
    }
  }
  // Drop events that exhausted retries
  const kept = items.filter((i) => i.retry_count < MAX_RETRIES);
  await save(kept);
}

export async function clearAll(): Promise<void> {
  await save([]);
}

export function computeBackoffMs(retry: number): number {
  // Exponential: 2s, 4s, 8s, 16s, 32s (cap 60s)
  return Math.min(60_000, 2_000 * Math.pow(2, retry));
}
