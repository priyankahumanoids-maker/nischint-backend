import React, { useState, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../../api';
import { Shield, Loader2, AlertTriangle, MapPin, Phone } from 'lucide-react';

export default function MobileSOS() {
  const navigate = useNavigate();
  const [phase, setPhase] = useState('ready'); // ready | holding | sending | sent | failed
  const [holdProgress, setHoldProgress] = useState(0);
  const [result, setResult] = useState(null);
  const holdTimer = useRef(null);
  const progressTimer = useRef(null);
  const HOLD_DURATION = 3000;

  const startHold = useCallback(() => {
    setPhase('holding');
    setHoldProgress(0);

    // Haptic feedback
    if (navigator.vibrate) navigator.vibrate(50);

    const startTime = Date.now();
    progressTimer.current = setInterval(() => {
      const elapsed = Date.now() - startTime;
      const progress = Math.min(elapsed / HOLD_DURATION, 1);
      setHoldProgress(progress);
      if (progress >= 1) {
        clearInterval(progressTimer.current);
        triggerSOS();
      }
    }, 30);
  }, []);

  const cancelHold = useCallback(() => {
    if (phase === 'holding') {
      clearInterval(progressTimer.current);
      setPhase('ready');
      setHoldProgress(0);
    }
  }, [phase]);

  const triggerSOS = async () => {
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
        trigger_type: 'manual',
        lat, lng,
        message: 'Emergency SOS triggered',
      });
      setResult(res.data);
      setPhase('sent');
      if (navigator.vibrate) navigator.vibrate(200);
    } catch {
      setPhase('failed');
    }
  };

  return (
    <div className="flex flex-col items-center justify-center min-h-full px-6 py-8" data-testid="mobile-sos">
      {phase === 'ready' && (
        <>
          <Shield className="w-10 h-10 text-red-400 mb-4" />
          <h1 className="text-xl font-bold text-white mb-1">Emergency SOS</h1>
          <p className="text-sm text-slate-400 text-center mb-8">
            Press and hold the button for 3 seconds to trigger an emergency alert
          </p>

          <div className="relative">
            <button
              onPointerDown={startHold}
              onPointerUp={cancelHold}
              onPointerLeave={cancelHold}
              className="w-40 h-40 rounded-full bg-red-500 text-white flex items-center justify-center shadow-xl shadow-red-500/30 active:scale-95 transition-transform select-none touch-none"
              data-testid="sos-hold-btn"
            >
              <div className="text-center">
                <Shield className="w-10 h-10 mx-auto mb-1" />
                <span className="text-sm font-bold">HOLD FOR SOS</span>
              </div>
            </button>
          </div>

          <div className="mt-10 w-full space-y-3">
            <button
              onClick={() => navigate('/m/fake-call')}
              className="w-full p-3 rounded-2xl bg-purple-500/10 border border-purple-500/30 flex items-center gap-3 active:scale-[0.98] transition-transform"
              data-testid="sos-fake-call"
            >
              <Phone className="w-5 h-5 text-purple-400" />
              <div>
                <p className="text-xs font-medium text-white">Fake Call</p>
                <p className="text-[10px] text-slate-500">Simulate incoming call</p>
              </div>
            </button>
          </div>
        </>
      )}

      {phase === 'holding' && (
        <div className="flex flex-col items-center">
          <div className="relative w-44 h-44">
            <svg className="w-full h-full -rotate-90" viewBox="0 0 100 100">
              <circle cx="50" cy="50" r="45" fill="none" stroke="#1e293b" strokeWidth="4" />
              <circle
                cx="50" cy="50" r="45" fill="none"
                stroke="#ef4444" strokeWidth="4"
                strokeDasharray={`${holdProgress * 283} 283`}
                strokeLinecap="round"
                className="transition-all duration-75"
              />
            </svg>
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="w-32 h-32 rounded-full bg-red-500 flex items-center justify-center animate-pulse">
                <span className="text-2xl font-bold text-white">{Math.ceil((1 - holdProgress) * 3)}</span>
              </div>
            </div>
          </div>
          <p className="text-sm text-red-400 mt-4 font-medium animate-pulse">Keep holding...</p>
          <p className="text-[10px] text-slate-500 mt-1">Release to cancel</p>
        </div>
      )}

      {phase === 'sending' && (
        <div className="flex flex-col items-center">
          <Loader2 className="w-12 h-12 text-red-400 animate-spin mb-4" />
          <p className="text-lg font-bold text-white">Sending SOS...</p>
          <p className="text-sm text-slate-400 mt-1">Alerting your guardian network</p>
        </div>
      )}

      {phase === 'sent' && (
        <div className="flex flex-col items-center text-center" data-testid="sos-sent">
          <div className="w-16 h-16 rounded-full bg-red-500/20 flex items-center justify-center mb-4">
            <AlertTriangle className="w-8 h-8 text-red-400" />
          </div>
          <h2 className="text-xl font-bold text-white mb-1">SOS Sent</h2>
          <p className="text-sm text-slate-400 mb-4">
            {result?.guardians_notified || 0} guardians have been notified
          </p>
          {result?.guardian_notifications?.map((g, i) => (
            <div key={i} className="w-full p-2 rounded-xl bg-slate-800/40 border border-slate-700/40 mb-2 flex items-center gap-2">
              <div className="w-8 h-8 rounded-full bg-teal-500/20 flex items-center justify-center">
                <span className="text-xs text-teal-400 font-bold">{g.priority}</span>
              </div>
              <div className="text-left">
                <p className="text-xs text-white font-medium">{g.name}</p>
                <p className="text-[10px] text-slate-500">{g.relationship} — {g.channels?.join(', ')}</p>
              </div>
            </div>
          ))}
          <button
            onClick={() => { setPhase('ready'); setResult(null); }}
            className="mt-4 px-6 py-2 rounded-full bg-slate-800 text-white text-sm font-medium active:scale-95 transition-transform"
          >
            Done
          </button>
        </div>
      )}

      {phase === 'failed' && (
        <div className="flex flex-col items-center text-center">
          <AlertTriangle className="w-12 h-12 text-amber-400 mb-4" />
          <h2 className="text-lg font-bold text-white mb-1">SOS Failed</h2>
          <p className="text-sm text-slate-400 mb-4">Trying again...</p>
          <button onClick={triggerSOS} className="px-6 py-2 rounded-full bg-red-500 text-white text-sm font-bold active:scale-95 transition-transform" data-testid="sos-retry">
            Retry SOS
          </button>
        </div>
      )}
    </div>
  );
}
