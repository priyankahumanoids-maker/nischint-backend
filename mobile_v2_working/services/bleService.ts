/**
 * NISCHINT BLE Service — Device scanning, connection, pairing, and heartbeat scheduler.
 * Mobile-bridged: BLE stays on device, backend handles truth/mapping/escalation.
 *
 * Flow: BLE scan → connect → register on backend → bind to user → listen for events
 */
import { Platform } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { wearableService } from './endpoints';
import { handleBleEvent } from './bleEventHandler';

// ── Types ──

export interface BleDevice {
  id: string;           // BLE peripheral ID (device_uid)
  name: string | null;
  rssi: number;
  backendId?: string;   // UUID from /api/wearable/register
  bound?: boolean;
}

export interface PairedDevice {
  deviceUid: string;
  backendId: string;
  name: string;
  battery: number | null;
  connected: boolean;
  lastSeen: string | null;
}

type BleState = {
  scanning: boolean;
  connected: boolean;
  currentDevice: PairedDevice | null;
};

// ── Storage Keys ──

const PAIRED_KEY = 'nischint:ble_paired_device';
const HEARTBEAT_INTERVAL_MS = 60_000; // 1 minute

// ── State ──

let _state: BleState = {
  scanning: false,
  connected: false,
  currentDevice: null,
};

let _bleManager: any = null;
let _heartbeatTimer: ReturnType<typeof setInterval> | null = null;
let _listeners: Array<(state: BleState) => void> = [];

// ── State Management ──

function _setState(partial: Partial<BleState>) {
  _state = { ..._state, ...partial };
  _listeners.forEach((fn) => fn(_state));
}

export function subscribeBleState(fn: (state: BleState) => void) {
  _listeners.push(fn);
  return () => {
    _listeners = _listeners.filter((l) => l !== fn);
  };
}

export function getBleState(): BleState {
  return { ..._state };
}

// ── BLE Manager Init ──

async function _ensureManager(): Promise<any> {
  if (_bleManager) return _bleManager;

  if (Platform.OS === 'web') {
    console.warn('[BLE] Not supported on web');
    return null;
  }

  try {
    const { BleManager } = require('react-native-ble-plx');
    _bleManager = new BleManager();
    return _bleManager;
  } catch (e) {
    console.warn('[BLE] react-native-ble-plx not available:', e);
    return null;
  }
}

// ── Scanning ──

export async function startScan(
  onDeviceFound: (device: BleDevice) => void,
  timeoutMs: number = 10_000,
): Promise<void> {
  const manager = await _ensureManager();
  if (!manager) return;

  _setState({ scanning: true });
  const seen = new Set<string>();

  manager.startDeviceScan(
    null, // scan all service UUIDs
    { allowDuplicates: false },
    (error: any, device: any) => {
      if (error) {
        console.warn('[BLE_SCAN_ERROR]', error.message);
        return;
      }
      if (!device || seen.has(device.id)) return;
      seen.add(device.id);

      // Only report devices with names (filter noise)
      if (device.name || device.localName) {
        onDeviceFound({
          id: device.id,
          name: device.name || device.localName,
          rssi: device.rssi || -100,
        });
      }
    },
  );

  // Auto-stop after timeout
  setTimeout(() => stopScan(), timeoutMs);
}

export function stopScan() {
  if (_bleManager) {
    try {
      _bleManager.stopDeviceScan();
    } catch {}
  }
  _setState({ scanning: false });
}

// ── Pairing Flow ──

/**
 * Full pairing flow:
 * 1. Connect to BLE device
 * 2. Register on backend (POST /api/wearable/register)
 * 3. Bind to current user (POST /api/wearable/bind)
 * 4. Save pairing to AsyncStorage
 * 5. Start heartbeat + event monitoring
 */
export async function pairDevice(
  bleDevice: BleDevice,
  userId: string,
): Promise<{ success: boolean; error?: string }> {
  const manager = await _ensureManager();

  try {
    // 1. Connect BLE
    let connectedDevice: any = null;
    if (manager) {
      stopScan();
      connectedDevice = await manager.connectToDevice(bleDevice.id, {
        timeout: 10_000,
      });
      await connectedDevice.discoverAllServicesAndCharacteristics();
    }

    // 2. Register on backend
    const regRes = await wearableService.register(bleDevice.id);
    const backendId = regRes.data.device_id;

    // 3. Bind to user
    if (!regRes.data.linked_user) {
      await wearableService.bind(backendId, userId);
    }

    // 4. Save pairing
    const paired: PairedDevice = {
      deviceUid: bleDevice.id,
      backendId,
      name: bleDevice.name || 'Nischint Band',
      battery: null,
      connected: true,
      lastSeen: new Date().toISOString(),
    };
    await AsyncStorage.setItem(PAIRED_KEY, JSON.stringify(paired));

    _setState({ connected: true, currentDevice: paired });

    // 5. Start heartbeat + event listener
    _startHeartbeat(backendId);
    if (connectedDevice) {
      _startEventMonitoring(connectedDevice, backendId);
    }

    console.log('[BLE_PAIRED]', bleDevice.id, '->', backendId);
    return { success: true };
  } catch (e: any) {
    console.error('[BLE_PAIR_FAIL]', e.message);
    return { success: false, error: e.message || 'Pairing failed' };
  }
}

// ── Reconnection ──

/**
 * Restore saved pairing on app launch.
 * Re-connects BLE if device is in range, otherwise stays paired (backend-only).
 */
export async function restorePairing(): Promise<boolean> {
  try {
    const stored = await AsyncStorage.getItem(PAIRED_KEY);
    if (!stored) return false;

    const paired: PairedDevice = JSON.parse(stored);
    _setState({ currentDevice: { ...paired, connected: false } });

    // Try BLE reconnect
    const manager = await _ensureManager();
    if (manager) {
      try {
        const device = await manager.connectToDevice(paired.deviceUid, {
          timeout: 5_000,
        });
        await device.discoverAllServicesAndCharacteristics();

        _setState({ connected: true, currentDevice: { ...paired, connected: true } });
        _startHeartbeat(paired.backendId);
        _startEventMonitoring(device, paired.backendId);

        console.log('[BLE_RECONNECTED]', paired.deviceUid);
      } catch {
        // Device not in range — backend-only mode
        console.log('[BLE_RESTORE] Device not in range, backend-only mode');
        _startHeartbeat(paired.backendId); // heartbeat still runs (will send battery=null)
      }
    }

    return true;
  } catch {
    return false;
  }
}

// ── Unpair ──

export async function unpairDevice(): Promise<void> {
  _stopHeartbeat();

  if (_bleManager && _state.currentDevice) {
    try {
      await _bleManager.cancelDeviceConnection(_state.currentDevice.deviceUid);
    } catch {}
  }

  await AsyncStorage.removeItem(PAIRED_KEY);
  _setState({ connected: false, currentDevice: null });
  console.log('[BLE_UNPAIRED]');
}

// ── Heartbeat Scheduler ──

function _startHeartbeat(backendId: string) {
  _stopHeartbeat();

  // Immediate first heartbeat
  _sendHeartbeat(backendId);

  // Then every HEARTBEAT_INTERVAL_MS
  _heartbeatTimer = setInterval(() => _sendHeartbeat(backendId), HEARTBEAT_INTERVAL_MS);
}

function _stopHeartbeat() {
  if (_heartbeatTimer) {
    clearInterval(_heartbeatTimer);
    _heartbeatTimer = null;
  }
}

async function _sendHeartbeat(backendId: string) {
  try {
    let battery: number | undefined;
    let rssi: number | undefined;

    // Read battery from BLE if connected
    if (_bleManager && _state.currentDevice?.deviceUid) {
      try {
        const device = await _bleManager.readRSSIForDevice(_state.currentDevice.deviceUid);
        rssi = device?.rssi;
      } catch {}

      // Battery Service UUID: 0x180F, Battery Level Char: 0x2A19
      try {
        const char = await _bleManager.readCharacteristicForDevice(
          _state.currentDevice.deviceUid,
          '0000180f-0000-1000-8000-00805f9b34fb',
          '00002a19-0000-1000-8000-00805f9b34fb',
        );
        if (char?.value) {
          // Base64 decode single byte
          const decoded = atob(char.value);
          battery = decoded.charCodeAt(0);
        }
      } catch {}
    }

    await wearableService.heartbeat(backendId, battery, rssi);

    // Update local state
    if (_state.currentDevice) {
      const updated = {
        ..._state.currentDevice,
        battery: battery ?? _state.currentDevice.battery,
        lastSeen: new Date().toISOString(),
      };
      _setState({ currentDevice: updated });
      await AsyncStorage.setItem(PAIRED_KEY, JSON.stringify(updated));
    }
  } catch (e: any) {
    console.warn('[BLE_HEARTBEAT_FAIL]', e.message);
  }
}

// ── BLE Event Monitoring ──

/**
 * Subscribe to BLE characteristic notifications.
 * Maps GATT events to backend API calls via bleEventHandler.
 */
function _startEventMonitoring(device: any, backendId: string) {
  // Custom Nischint Safety Service UUID (configurable per hardware)
  const SAFETY_SERVICE = '0000ffe0-0000-1000-8000-00805f9b34fb';
  const BUTTON_CHAR = '0000ffe1-0000-1000-8000-00805f9b34fb';

  try {
    // Monitor button press characteristic
    device.monitorCharacteristicForService(
      SAFETY_SERVICE,
      BUTTON_CHAR,
      (error: any, char: any) => {
        if (error) {
          console.warn('[BLE_MONITOR_ERROR]', error.message);
          // Connection lost — try reconnect
          if (error.message?.includes('disconnected')) {
            _setState({ connected: false });
            _attemptReconnect(backendId);
          }
          return;
        }

        if (char?.value) {
          const decoded = atob(char.value);
          const eventByte = decoded.charCodeAt(0);
          handleBleEvent(backendId, eventByte);
        }
      },
    );
    console.log('[BLE_MONITORING] Started for', backendId);
  } catch (e: any) {
    console.warn('[BLE_MONITOR_SETUP_FAIL]', e.message);
  }
}

// ── Auto-Reconnect ──

let _reconnectAttempts = 0;
const MAX_RECONNECT = 5;
const RECONNECT_DELAYS = [2000, 5000, 10000, 20000, 30000];

async function _attemptReconnect(backendId: string) {
  if (_reconnectAttempts >= MAX_RECONNECT) {
    console.warn('[BLE_RECONNECT] Max attempts reached');
    return;
  }

  const delay = RECONNECT_DELAYS[_reconnectAttempts] || 30000;
  _reconnectAttempts++;

  setTimeout(async () => {
    if (!_state.currentDevice) return;

    try {
      const manager = await _ensureManager();
      if (!manager) return;

      const device = await manager.connectToDevice(_state.currentDevice.deviceUid, {
        timeout: 5_000,
      });
      await device.discoverAllServicesAndCharacteristics();

      _setState({ connected: true });
      _reconnectAttempts = 0;
      _startEventMonitoring(device, backendId);

      console.log('[BLE_RECONNECTED] After', _reconnectAttempts, 'attempts');
    } catch {
      _attemptReconnect(backendId);
    }
  }, delay);
}

// ── Cleanup ──

export function cleanupBle() {
  _stopHeartbeat();
  stopScan();

  if (_bleManager && _state.currentDevice) {
    try {
      _bleManager.cancelDeviceConnection(_state.currentDevice.deviceUid);
    } catch {}
  }

  _setState({ scanning: false, connected: false });
}
