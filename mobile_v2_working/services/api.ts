// API Client with auth interceptors
import axios from 'axios';
import * as SecureStore from 'expo-secure-store';
import { Platform } from 'react-native';
import { router } from 'expo-router';

const API_BASE = process.env.EXPO_PUBLIC_API_URL || 'https://nischint.care';

console.log('[API_BASE]', API_BASE);

const api = axios.create({
  baseURL: `${API_BASE}/api`,
  timeout: 15000,
  headers: { 'Content-Type': 'application/json' },
});

// Endpoints that must NOT carry an Authorization header
const PUBLIC_PATHS = ['/auth/register', '/auth/login', '/auth/cognito-status'];

// Lazily import the auth store to avoid circular dependency
let _getToken: (() => string | null) | null = null;
let _clearAuth: (() => Promise<void>) | null = null;

const getAuthHelpers = () => {
  if (!_getToken) {
    const { useAuthStore } = require('../stores/authStore');
    _getToken = () => useAuthStore.getState().token;
    _clearAuth = async () => {
      useAuthStore.getState().logout();
    };
  }
  return { getToken: _getToken!, clearAuth: _clearAuth! };
};

const isLocalPreviewToken = (token?: string | null) => Boolean(token?.endsWith('.local'));

// Request interceptor — attach token only for authenticated endpoints
api.interceptors.request.use(
  async (config) => {
    const fullUrl = `${config.baseURL || ''}${config.url || ''}`;
    console.log(`[HTTP] ${config.method?.toUpperCase()} ${fullUrl}`);

    // Skip auth header for public endpoints
    const url = config.url || '';
    if (PUBLIC_PATHS.some((p) => url.includes(p))) {
      return config;
    }

    let token: string | null = null;

    // 1. Try in-memory store (fastest, always up-to-date after login)
    try {
      const { getToken } = getAuthHelpers();
      token = getToken();
    } catch {}

    // 2. Fallback to persistent storage if store is empty
    if (!token) {
      try {
        if (Platform.OS === 'web') {
          token = typeof localStorage !== 'undefined' ? localStorage.getItem('nischint_token') : null;
        } else {
          token = await SecureStore.getItemAsync('nischint_token');
        }
      } catch {}
    }

    if (isLocalPreviewToken(token)) {
      console.log('[HTTP] Local preview token detected; skipping Authorization header');
      return config;
    }

    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error),
);

// Response interceptor — surgically clear auth ONLY on real credentials
// failures.
//
// The backend distinguishes:
//   • `"Could not validate credentials"` / `"Token expired"` / `"Invalid token"`
//     → JWT is dead → user must re-login.
//   • `"Not authenticated"` → request was anonymous (race condition,
//     missed header, etc.) → don't kill a fresh session.
//   • 403 → valid token, wrong role/permission → caller's job to handle,
//     never logout.
const CREDENTIAL_FAILURE_HINTS = [
  'could not validate credentials',
  'token expired',
  'invalid token',
  'token has expired',
  'signature has expired',
];

const isCredentialsFailure = (error: any): boolean => {
  if (error?.response?.status !== 401) return false;
  const detail = String(error?.response?.data?.detail || '').toLowerCase();
  return CREDENTIAL_FAILURE_HINTS.some((h) => detail.includes(h));
};

api.interceptors.response.use(
  (res) => {
    console.log(`[HTTP] ${res.status} ${res.config?.url}`);
    return res;
  },
  async (error) => {
    const status = error.response?.status || 'NETWORK';
    const url = error.config?.url || error.config?.baseURL || 'unknown';
    const urlText = String(url);

    let token: string | null = null;
    try {
      const { getToken } = getAuthHelpers();
      token = getToken();
    } catch {}

    const isDemoGeofenceAuthNoise =
      isLocalPreviewToken(token) &&
      status === 401 &&
      urlText.includes('/geofence/location-update');

    if (isDemoGeofenceAuthNoise) {
      console.log(`[HTTP SKIP] ${status} ${urlText}`, error.message);
    } else {
      console.error(`[HTTP ERROR] ${status} ${urlText}`, error.message);
    }

    if (isLocalPreviewToken(token)) {
      console.log('[AUTH] Local preview API error ignored for auth routing:', status, url);
      return Promise.reject(error);
    }

    if (isCredentialsFailure(error)) {
      // Real session death — clear stored token + in-memory state and
      // bounce to login.
      try {
        if (Platform.OS === 'web') {
          localStorage.removeItem('nischint_token');
        } else {
          await SecureStore.deleteItemAsync('nischint_token');
        }
      } catch {}
      try {
        const { clearAuth } = getAuthHelpers();
        await clearAuth();
      } catch {}
      try {
        router.replace('/(auth)/login');
      } catch {}
    } else if (error.response?.status === 401) {
      console.log('[AUTH] 401 ignored (not a credentials failure):', error.response?.data?.detail);
    }
    return Promise.reject(error);
  },
);

export default api;
export { API_BASE };
