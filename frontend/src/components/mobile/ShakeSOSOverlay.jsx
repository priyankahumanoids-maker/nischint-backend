import React, { useState, useEffect, useRef, useCallback } from 'react';
import api from '../../api';
import { Shield, X, Loader2, AlertTriangle, CheckCircle } from 'lucide-react';

const COUNTDOWN_SECONDS = 3;

export default function ShakeSOSOverlay({ visible, onCancel, onComplete }) {
  const [phase, setPhase] = useState('countdown'); // countdown | sending | sent | failed
  const [countdown, setCountdown] = useState(COUNTDOWN_SECONDS);
  const timerRef = useRef(null);
  const cancelledRef = useRef(false);

  // Reset state when shown
  useEffect(() => {
    if (visible) {
      cancelledRef.current = false;
      setPhase('countdown');
      setCountdown(COUNTDOWN_SECONDS);
    }
  }, [visible]);

  // Countdown timer
  useEffect(() => {
    if (!visible || phase !== 'countdown') return;

    if (countdown <= 0) {
      triggerSOS();
      return;
    }

    timerRef.current = setTimeout(() => {
      if (!cancelledRef.current) {
        setCountdown(c => c - 1);
      }
    }, 1000);

    // Haptic on each tick
    if (navigator.vibrate) navigator.vibrate(100);

    return () => clearTimeout(timerRef.current);
  }, [visible, phase, countdown]);

  const triggerSOS = async () => {
    if (cancelledRef.current) return;
    setPhase('sending');

    if (navigator.vibrate) navigator.vibrate([100, 50, 100, 50, 200]);

    try {
      let lat = null, lng = null;
      try {
        const pos = await new Promise((resolve, reject) =>
          navigator.geolocation.getCurrentPosition(resolve, reject, { timeout: 5000 })
        );
        lat = pos.coords.latitude;
        lng = pos.coords.longitude;
      } catch { /* location unavailable */ }

      const res = await api.post('/safety-events/sos', {
        trigger_type: 'shake',
        lat, lng,
        message: 'Shake-triggered Emergency SOS',
      });

      setPhase('sent');
      if (navigator.vibrate) navigator.vibrate(300);

      setTimeout(() => {
        onComplete?.(res.data);
      }, 2500);
    } catch {
      setPhase('failed');
    }
  };

  const handleCancel = () => {
    cancelledRef.current = true;
    clearTimeout(timerRef.current);
    setPhase('countdown');
    setCountdown(COUNTDOWN_SECONDS);
    onCancel?.();
  };

  if (!visible) return null;

  const progress = (COUNTDOWN_SECONDS - countdown) / COUNTDOWN_SECONDS;

  return (
    <div className="fixed inset-0 z-[9999] bg-slate-950/95 backdrop-blur-xl flex flex-col items-center justify-center" data-testid="shake-sos-overlay">
      {phase === 'countdown' && (
        <>
          {/* Animated ring */}
          <div className="relative w-48 h-48 mb-6">
            <svg className="w-full h-full -rotate-90" viewBox="0 0 100 100">
              <circle cx="50" cy="50" r="44" fill="none" stroke="#1e293b" strokeWidth="3" />
              <circle
                cx="50" cy="50" r="44" fill="none"
                stroke="#ef4444" strokeWidth="3"
                strokeDasharray={`${progress * 276.5} 276.5`}
                strokeLinecap="round"
                className="transition-all duration-1000 ease-linear"
              />
            </svg>
            <div className="absolute inset-0 flex flex-col items-center justify-center">
              <div className="w-32 h-32 rounded-full bg-red-500/20 border-2 border-red-500/40 flex flex-col items-center justify-center animate-pulse">
                <span className="text-5xl font-bold text-red-400 font-mono">{countdown}</span>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2 mb-2">
            <Shield className="w-5 h-5 text-red-400" />
            <span className="text-lg font-bold text-white">SHAKE DETECTED</span>
          </div>
          <p className="text-sm text-slate-400 text-center px-6 mb-8">
            SOS will trigger in {countdown} seconds
          </p>

          <button
            onClick={handleCancel}
            className="px-10 py-3.5 rounded-2xl bg-slate-800 border border-slate-600 text-white font-bold text-sm flex items-center gap-2 active:scale-95 transition-transform"
            data-testid="shake-sos-cancel"
          >
            <X className="w-5 h-5" /> Cancel
          </button>

          <p className="text-[10px] text-slate-600 mt-4">Tap cancel if this was accidental</p>
        </>
      )}

      {phase === 'sending' && (
        <div className="flex flex-col items-center">
          <Loader2 className="w-14 h-14 text-red-400 animate-spin mb-4" />
          <p className="text-lg font-bold text-white">Sending SOS...</p>
          <p className="text-sm text-slate-400 mt-1">Alerting your guardian network</p>
        </div>
      )}

      {phase === 'sent' && (
        <div className="flex flex-col items-center text-center px-6" data-testid="shake-sos-sent">
          <div className="w-16 h-16 rounded-full bg-red-500/20 flex items-center justify-center mb-4">
            <CheckCircle className="w-8 h-8 text-red-400" />
          </div>
          <h2 className="text-xl font-bold text-white mb-1">SOS Activated</h2>
          <p className="text-sm text-slate-400">Your guardians have been alerted</p>
        </div>
      )}

      {phase === 'failed' && (
        <div className="flex flex-col items-center text-center px-6">
          <AlertTriangle className="w-12 h-12 text-amber-400 mb-4" />
          <h2 className="text-lg font-bold text-white mb-1">SOS Failed</h2>
          <p className="text-sm text-slate-400 mb-4">Could not send alert</p>
          <button
            onClick={() => { setPhase('countdown'); setCountdown(0); }}
            className="px-6 py-2 rounded-full bg-red-500 text-white text-sm font-bold active:scale-95 transition-transform mb-3"
            data-testid="shake-sos-retry"
          >
            Retry
          </button>
          <button onClick={handleCancel} className="text-xs text-slate-500">
            Dismiss
          </button>
        </div>
      )}
    </div>
  );
}
