import { useEffect, useRef, useCallback } from 'react';

const SHAKE_THRESHOLD = 25;
const SHAKE_COUNT_THRESHOLD = 3;
const SHAKE_WINDOW_MS = 800;
const COOLDOWN_MS = 5000;

export default function useShakeDetector(onShake, enabled = true) {
  const shakeTimestamps = useRef([]);
  const lastTrigger = useRef(0);
  const onShakeRef = useRef(onShake);
  onShakeRef.current = onShake;

  const handleMotion = useCallback((e) => {
    if (!enabled) return;

    const acc = e.accelerationIncludingGravity;
    if (!acc) return;

    const magnitude = Math.sqrt(
      (acc.x || 0) ** 2 + (acc.y || 0) ** 2 + (acc.z || 0) ** 2
    );

    if (magnitude > SHAKE_THRESHOLD) {
      const now = Date.now();
      shakeTimestamps.current.push(now);

      // Keep only recent shakes within window
      shakeTimestamps.current = shakeTimestamps.current.filter(
        t => now - t < SHAKE_WINDOW_MS
      );

      // Trigger if enough shakes detected and cooldown passed
      if (
        shakeTimestamps.current.length >= SHAKE_COUNT_THRESHOLD &&
        now - lastTrigger.current > COOLDOWN_MS
      ) {
        lastTrigger.current = now;
        shakeTimestamps.current = [];
        onShakeRef.current?.();
      }
    }
  }, [enabled]);

  useEffect(() => {
    if (!enabled) return;

    // Request permission on iOS 13+
    if (typeof DeviceMotionEvent !== 'undefined' && typeof DeviceMotionEvent.requestPermission === 'function') {
      // Permission will be requested on first user interaction
      const requestOnInteraction = () => {
        DeviceMotionEvent.requestPermission()
          .then(state => {
            if (state === 'granted') {
              window.addEventListener('devicemotion', handleMotion);
            }
          })
          .catch(() => {});
        window.removeEventListener('click', requestOnInteraction);
      };
      window.addEventListener('click', requestOnInteraction);
      return () => {
        window.removeEventListener('click', requestOnInteraction);
        window.removeEventListener('devicemotion', handleMotion);
      };
    }

    window.addEventListener('devicemotion', handleMotion);
    return () => window.removeEventListener('devicemotion', handleMotion);
  }, [enabled, handleMotion]);
}
