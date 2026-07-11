// Auth Store using Zustand
import { create } from 'zustand';
import * as SecureStore from 'expo-secure-store';
import { Platform } from 'react-native';
import { authService } from '../services/endpoints';

type ProfileMode = 'women' | 'kids' | 'parents' | 'senior' | 'family';

function roleToProfileMode(role?: string): ProfileMode {
  if (role === 'child') return 'kids';
  if (role === 'guardian') return 'parents';
  if (role === 'woman') return 'women';
  if (role === 'senior') return 'senior';
  if (role === 'family') return 'family';
  return 'parents';
}

interface User {
  id: string;
  email: string;
  role: string;
  full_name: string;
}

interface AuthState {
  token: string | null;
  user: User | null;
  profileMode: ProfileMode;
  isLoading: boolean;
  isReady: boolean;

  setProfileMode: (mode: ProfileMode) => void;
  startLocalPreview: (mode: ProfileMode) => Promise<void>;
  login: (email: string, password: string) => Promise<void>;
  register: (data: { email: string; password: string; full_name: string; phone?: string }) => Promise<void>;
  logout: () => Promise<void>;
  loadToken: () => Promise<void>;
}

// ── Storage keys ──
const KEYS = {
  token: 'nischint_token',
  user: 'nischint_user',
  profile: 'nischint_profile',
} as const;

// ── Storage helpers ──
const storage = {
  set: async (key: string, value: string) => {
    if (Platform.OS === 'web') {
      localStorage.setItem(key, value);
    } else {
      await SecureStore.setItemAsync(key, value);
    }
  },
  get: async (key: string): Promise<string | null> => {
    if (Platform.OS === 'web') {
      return typeof localStorage !== 'undefined' ? localStorage.getItem(key) : null;
    }
    return SecureStore.getItemAsync(key);
  },
  remove: async (key: string) => {
    if (Platform.OS === 'web') {
      localStorage.removeItem(key);
    } else {
      await SecureStore.deleteItemAsync(key);
    }
  },
};

// Wipe ALL auth-related keys from storage
const clearAllStorage = async () => {
  console.log('[AUTH] Clearing all stored auth data');
  await Promise.all([
    storage.remove(KEYS.token),
    storage.remove(KEYS.user),
    storage.remove(KEYS.profile),
  ]);
};

const parseJwt = (token: string): User | null => {
  try {
    const base64Url = token.split('.')[1];
    const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/');
    const padded = base64 + '='.repeat((4 - (base64.length % 4)) % 4);

    let jsonStr: string;
    if (typeof atob === 'function') {
      jsonStr = atob(padded);
    } else {
      const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=';
      let output = '';
      for (let i = 0; i < padded.length; i += 4) {
        const a = chars.indexOf(padded[i]);
        const b = chars.indexOf(padded[i + 1]);
        const c = chars.indexOf(padded[i + 2]);
        const d = chars.indexOf(padded[i + 3]);
        output += String.fromCharCode((a << 2) | (b >> 4));
        if (c !== 64) output += String.fromCharCode(((b & 15) << 4) | (c >> 2));
        if (d !== 64) output += String.fromCharCode(((c & 3) << 6) | d);
      }
      jsonStr = decodeURIComponent(
        output.split('').map((c) => '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2)).join('')
      );
    }

    const payload = JSON.parse(jsonStr);
    const user = {
      id: payload.sub,
      email: payload.email,
      role: payload.role || '',
      full_name: payload.full_name || payload.name || '',
    };
    console.log('[AUTH] parseJwt result:', JSON.stringify(user));
    return user;
  } catch (e) {
    console.error('[AUTH] parseJwt FAILED:', e);
    return null;
  }
};

const encodeJwtPart = (value: string) => {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
  let output = '';
  for (let i = 0; i < value.length; i += 3) {
    const a = value.charCodeAt(i);
    const b = i + 1 < value.length ? value.charCodeAt(i + 1) : NaN;
    const c = i + 2 < value.length ? value.charCodeAt(i + 2) : NaN;
    output += chars[a >> 2];
    output += chars[((a & 3) << 4) | ((b || 0) >> 4)];
    output += Number.isNaN(b) ? '=' : chars[((b & 15) << 2) | ((c || 0) >> 6)];
    output += Number.isNaN(c) ? '=' : chars[c & 63];
  }
  return output.replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
};

const createLocalPreviewToken = (user: User) => {
  const header = encodeJwtPart(JSON.stringify({ alg: 'none', typ: 'JWT' }));
  const payload = encodeJwtPart(JSON.stringify({
    sub: user.id,
    email: user.email,
    role: user.role,
    full_name: user.full_name,
    name: user.full_name,
  }));
  return `${header}.${payload}.local`;
};

const isLocalPreviewToken = (token?: string | null) => Boolean(token?.endsWith('.local'));

export const useAuthStore = create<AuthState>((set) => ({
  token: null,
  user: null,
  profileMode: 'parents',
  isLoading: false,
  isReady: false,

  setProfileMode: async (mode: ProfileMode) => {
    await storage.set(KEYS.profile, mode);
    set({ profileMode: mode });
  },

  startLocalPreview: async (mode: ProfileMode) => {
    const role =
      mode === 'kids' ? 'child' :
      mode === 'women' ? 'woman' :
      mode === 'senior' ? 'senior' :
      mode === 'family' ? 'family' :
      'guardian';
    const user: User = {
      id: 'local-preview',
      email: 'local.preview@nischint.app',
      role,
      full_name: role === 'guardian' ? 'Rajesh Sharma' : 'Protected Member',
    };
    const token = createLocalPreviewToken(user);
    await Promise.all([
      storage.set(KEYS.token, token),
      storage.set(KEYS.user, JSON.stringify(user)),
      storage.set(KEYS.profile, mode),
    ]);
    set({ token, user, profileMode: mode, isReady: true, isLoading: false });
  },

  login: async (email, password) => {
    set({ isLoading: true });
    try {
      const res = await authService.login(email, password);
      const { access_token } = res.data;
      console.log('[LOGIN] Response role:', res.data.role);

      await storage.set(KEYS.token, access_token);
      const decodedUser = parseJwt(access_token);
      console.log('[LOGIN] SET USER:', JSON.stringify(decodedUser));

      if (decodedUser) await storage.set(KEYS.user, JSON.stringify(decodedUser));

      const profileMode = roleToProfileMode(decodedUser?.role);
      await storage.set(KEYS.profile, profileMode);
      set({ token: access_token, user: decodedUser, profileMode, isLoading: false });
    } catch (e) {
      set({ isLoading: false });
      throw e;
    }
  },

  register: async (data) => {
    set({ isLoading: true });
    try {
      const res = await authService.register(data);
      const { access_token } = res.data;
      if (!access_token) throw new Error('No access token received from server');

      await storage.set(KEYS.token, access_token);
      const user = parseJwt(access_token);
      if (user) await storage.set(KEYS.user, JSON.stringify(user));

      const profileMode = roleToProfileMode(user?.role);
      await storage.set(KEYS.profile, profileMode);
      set({ token: access_token, user, profileMode, isLoading: false });
    } catch (e: any) {
      set({ isLoading: false });
      if (e.response) throw e;
      throw new Error(e.message || 'Network error — please check your connection');
    }
  },

  logout: async () => {
    await clearAllStorage();
    set({ token: null, user: null, profileMode: 'parents', isReady: true });
  },

  loadToken: async () => {
    const token = await storage.get(KEYS.token);
    if (!token) {
      console.log('[AUTH] loadToken — no stored token');
      set({ isReady: true });
      return;
    }

    // JWT is the source of truth for role — always parse it first
    if (isLocalPreviewToken(token)) {
      const storedUser = await storage.get(KEYS.user);
      const storedProfile = await storage.get(KEYS.profile);
      const decodedUser = parseJwt(token);
      const user = storedUser ? JSON.parse(storedUser) as User : decodedUser;
      const profileMode = (
        storedProfile === 'women' ||
        storedProfile === 'kids' ||
        storedProfile === 'parents' ||
        storedProfile === 'senior' ||
        storedProfile === 'family'
      ) ? storedProfile : roleToProfileMode(user?.role);
      console.log('[AUTH] loadToken - local preview session restored');
      set({ token, user, profileMode, isReady: true, isLoading: false });
      return;
    }

    let decodedUser = parseJwt(token);
    console.log('[AUTH] loadToken — JWT user:', JSON.stringify(decodedUser));
    console.log('[AUTH] SET USER:', JSON.stringify(decodedUser));

    if (decodedUser?.role) {
      // JWT has role — save and use it, but protect existing guardian
      await storage.set(KEYS.user, JSON.stringify(decodedUser));
      const profileMode = roleToProfileMode(decodedUser.role);
      set((prev) => {
        if (prev.user?.role === 'guardian' && decodedUser?.role !== 'guardian') {
          console.log('[AUTH] loadToken — BLOCKED overwrite of guardian user');
          return { ...prev, isReady: true };
        }
        return { token, user: decodedUser, profileMode, isReady: true };
      });
      return;
    }

    // JWT missing role — fetch fresh from server
    console.log('[AUTH] loadToken — JWT has no role, calling /auth/me');
    try {
      const res = await authService.getMe();
      const me = res.data;
      console.log('[AUTH] loadToken — /auth/me:', JSON.stringify(me));
      decodedUser = {
        id: me.id || decodedUser?.id || '',
        email: me.email || decodedUser?.email || '',
        role: me.role || '',
        full_name: me.full_name || decodedUser?.full_name || '',
      };
      console.log('[AUTH] SET USER from /me:', JSON.stringify(decodedUser));
      await storage.set(KEYS.user, JSON.stringify(decodedUser));
      const profileMode = roleToProfileMode(decodedUser.role);
      set((prev) => {
        if (prev.user?.role === 'guardian' && decodedUser?.role !== 'guardian') {
          console.log('[AUTH] loadToken/me — BLOCKED overwrite of guardian user');
          return { ...prev, isReady: true };
        }
        return { token, user: decodedUser, profileMode, isReady: true };
      });
    } catch (e) {
      console.warn('[AUTH] loadToken — /auth/me failed, forcing logout');
      await clearAllStorage();
      set({ token: null, user: null, isReady: true });
    }
  },
}));
