/**
 * NISCHINT BLE Event Handler — Maps raw BLE characteristic bytes to backend API calls.
 * Translates hardware signals into the wearable event contract.
 *
 * Backend contract: POST /api/wearable/event
 * Payload: { device_id, event_type, event_id, payload, client_timestamp }
 */
import { wearableService } from './endpoints';

// ── Event Byte Map (from GATT characteristic) ──

const EVENT_BYTE_MAP: Record<number, string> = {
  0x01: 'BUTTON_PRESS',          // Single press
  0x02: 'BUTTON_LONG_PRESS',     // Long press (3s+)
  0x03: 'BUTTON_DOUBLE_PRESS',   // Double tap (custom)
  0x10: 'FALL_DETECTED',         // Accelerometer fall detection
  0x11: 'IMPACT_DETECTED',       // High-G impact
  0x20: 'TAMPER_DETECTED',       // Band removed / tamper switch
  0x30: 'HEARTRATE_ANOMALY',     // Heart rate out of range
  0x40: 'GEOFENCE_BREACH',       // Geofence exit (if device has GPS)
  0xFF: 'DEVICE_TEST',           // Hardware test signal
};

// ── Deduplication ──

const _processedEvents = new Set<string>();
const DEDUP_WINDOW_MS = 5_000; // 5-second dedup window for same event type

let _lastEventTimes: Record<string, number> = {};

function _isDuplicate(eventType: string): boolean {
  const now = Date.now();
  const last = _lastEventTimes[eventType] || 0;

  if (now - last < DEDUP_WINDOW_MS) {
    return true;
  }

  _lastEventTimes[eventType] = now;
  return false;
}

// ── UUID Generator ──

function _generateEventId(): string {
  // Lightweight UUID v4 for event idempotency
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

// ── Main Handler ──

/**
 * Process a raw BLE event byte and forward to backend.
 * Called by bleService when a GATT characteristic notification arrives.
 *
 * @param backendDeviceId - UUID from /api/wearable/register
 * @param eventByte - Raw byte from BLE characteristic
 * @param extraPayload - Optional additional data (accel, etc.)
 */
export async function handleBleEvent(
  backendDeviceId: string,
  eventByte: number,
  extraPayload?: Record<string, any>,
): Promise<void> {
  const eventType = EVENT_BYTE_MAP[eventByte];

  if (!eventType) {
    console.warn('[BLE_EVENT] Unknown event byte:', eventByte.toString(16));
    return;
  }

  // Client-side dedup (prevents rapid re-fires from noisy hardware)
  if (_isDuplicate(eventType)) {
    console.log('[BLE_EVENT_DEDUP] Skipping duplicate:', eventType);
    return;
  }

  const eventId = _generateEventId();
  const timestamp = new Date().toISOString();

  console.log(`[BLE_EVENT] ${eventType} (0x${eventByte.toString(16)}) -> backend`);

  try {
    const response = await wearableService.sendEvent(backendDeviceId, {
      event_type: eventType,
      event_id: eventId,
      payload: {
        trigger_source: 'wearable',
        raw_byte: eventByte,
        ...extraPayload,
      },
      client_timestamp: timestamp,
    });

    const data = response.data;

    console.log(
      `[BLE_EVENT_OK] ${eventType} -> ${data.alert_category}`,
      `guardians=${data.guardians_notified}`,
      data.escalation_triggered ? '(ESCALATION!)' : '',
    );
  } catch (e: any) {
    console.error('[BLE_EVENT_FAIL]', eventType, e.message);

    // Queue for retry if offline
    _queueFailedEvent(backendDeviceId, eventType, eventId, timestamp, extraPayload);
  }
}

// ── Manual Event Trigger (for testing or app-initiated wearable events) ──

/**
 * Trigger a wearable event directly by type name (no BLE byte needed).
 * Useful for testing or when the app simulates a wearable action.
 */
export async function triggerManualEvent(
  backendDeviceId: string,
  eventType: string,
  payload?: Record<string, any>,
): Promise<{ success: boolean; data?: any; error?: string }> {
  const eventId = _generateEventId();

  try {
    const response = await wearableService.sendEvent(backendDeviceId, {
      event_type: eventType,
      event_id: eventId,
      payload: {
        trigger_source: 'manual',
        ...payload,
      },
      client_timestamp: new Date().toISOString(),
    });

    return { success: true, data: response.data };
  } catch (e: any) {
    return { success: false, error: e.message };
  }
}

// ── Offline Queue ──

import AsyncStorage from '@react-native-async-storage/async-storage';

const QUEUE_KEY = 'nischint:ble_event_queue';

async function _queueFailedEvent(
  deviceId: string,
  eventType: string,
  eventId: string,
  timestamp: string,
  payload?: Record<string, any>,
) {
  try {
    const stored = await AsyncStorage.getItem(QUEUE_KEY);
    const queue = stored ? JSON.parse(stored) : [];

    queue.push({ deviceId, eventType, eventId, timestamp, payload });

    // Cap queue at 50 events
    if (queue.length > 50) queue.shift();

    await AsyncStorage.setItem(QUEUE_KEY, JSON.stringify(queue));
    console.log('[BLE_QUEUE] Event queued for retry:', eventType);
  } catch {}
}

/**
 * Flush queued events when connectivity restores.
 * Call on app foregrounding or network recovery.
 */
export async function flushEventQueue(backendDeviceId: string): Promise<number> {
  try {
    const stored = await AsyncStorage.getItem(QUEUE_KEY);
    if (!stored) return 0;

    const queue = JSON.parse(stored);
    if (!queue.length) return 0;

    let sent = 0;

    for (const evt of queue) {
      try {
        await wearableService.sendEvent(backendDeviceId, {
          event_type: evt.eventType,
          event_id: evt.eventId,
          payload: { trigger_source: 'wearable_retry', ...evt.payload },
          client_timestamp: evt.timestamp,
        });
        sent++;
      } catch {
        break; // Still offline — stop trying
      }
    }

    if (sent === queue.length) {
      await AsyncStorage.removeItem(QUEUE_KEY);
    } else {
      // Remove only sent events
      await AsyncStorage.setItem(QUEUE_KEY, JSON.stringify(queue.slice(sent)));
    }

    console.log(`[BLE_QUEUE_FLUSH] Sent ${sent}/${queue.length} queued events`);
    return sent;
  } catch {
    return 0;
  }
}
