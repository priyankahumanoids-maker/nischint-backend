import { useEffect, useRef, useCallback } from 'react';
import { toast } from 'sonner';
import { requestPushToken, onForegroundMessage } from '../lib/firebase';
import api from '../api';

/**
 * Hook to manage push notification lifecycle:
 * 1. Request notification permission
 * 2. Get FCM token
 * 3. Register token with backend
 * 4. Handle foreground messages with toast
 */
export default function usePushNotifications() {
  const registeredRef = useRef(false);

  const registerToken = useCallback(async () => {
    if (registeredRef.current) return;
    if (!('Notification' in window)) return;

    try {
      const token = await requestPushToken();
      if (!token) return;

      await api.post('/device/register', {
        device_token: token,
        device_type: 'web',
      });

      registeredRef.current = true;
      console.log('[Push] FCM token registered');
    } catch (err) {
      console.warn('[Push] Registration failed:', err.message);
    }
  }, []);

  useEffect(() => {
    registerToken();

    // Handle foreground messages with toast
    const unsubscribe = onForegroundMessage((payload) => {
      const { title, body } = payload.notification || {};
      const data = payload.data || {};
      const tag = data.tag || '';

      // Choose toast style based on alert type
      if (tag === 'nischint-sos') {
        toast.error(title || 'SOS Alert', {
          description: body,
          duration: 10000,
          action: {
            label: 'View',
            onClick: () => window.location.href = data.url || '/m/home',
          },
        });
      } else if (tag === 'nischint-risk') {
        toast.warning(title || 'Risk Alert', {
          description: body,
          duration: 8000,
        });
      } else {
        toast.info(title || 'Nischint', {
          description: body,
          duration: 5000,
        });
      }
    });

    return () => {
      if (typeof unsubscribe === 'function') unsubscribe();
    };
  }, [registerToken]);
}
