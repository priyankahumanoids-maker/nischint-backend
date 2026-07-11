import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  Phone, PhoneOff, Mic, MicOff, Volume2, VolumeX,
  User, Shield, X,
} from 'lucide-react';
import api from '../api';
import { toast } from 'sonner';

const RING_DURATION = 30; // seconds before auto-decline

const FakeCallScreen = ({ callData, onClose }) => {
  const [phase, setPhase] = useState('ringing'); // ringing | active | ended
  const [callTimer, setCallTimer] = useState(0);
  const [ringTimer, setRingTimer] = useState(0);
  const [muted, setMuted] = useState(false);
  const [speakerOn, setSpeakerOn] = useState(false);
  const [showPostCall, setShowPostCall] = useState(false);
  const timerRef = useRef(null);
  const ringRef = useRef(null);
  const audioRef = useRef(null);

  const callerName = callData?.caller_name || 'Unknown';
  const callerLabel = callData?.caller_label || 'Incoming Call';
  const callId = callData?.call_id;

  // Ring animation
  useEffect(() => {
    if (phase !== 'ringing') return;
    ringRef.current = setInterval(() => {
      setRingTimer(prev => {
        if (prev >= RING_DURATION) {
          handleDecline();
          return prev;
        }
        return prev + 1;
      });
    }, 1000);
    return () => clearInterval(ringRef.current);
  }, [phase]);

  // Call timer
  useEffect(() => {
    if (phase !== 'active') return;
    timerRef.current = setInterval(() => setCallTimer(t => t + 1), 1000);
    return () => clearInterval(timerRef.current);
  }, [phase]);

  // Prevent body scroll
  useEffect(() => {
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = ''; };
  }, []);

  const formatTime = (s) => {
    const m = Math.floor(s / 60);
    const sec = s % 60;
    return `${m}:${sec.toString().padStart(2, '0')}`;
  };

  const handleAnswer = useCallback(() => {
    clearInterval(ringRef.current);
    setPhase('active');
  }, []);

  const handleDecline = useCallback(() => {
    clearInterval(ringRef.current);
    clearInterval(timerRef.current);
    if (callId) {
      api.post(`/fake-call/complete/${callId}`, { answered: false, duration_seconds: 0, send_alert: false }).catch(() => {});
    }
    onClose?.();
  }, [callId, onClose]);

  const handleEndCall = useCallback(() => {
    clearInterval(timerRef.current);
    setPhase('ended');
    setShowPostCall(true);
  }, []);

  const handlePostCallAction = useCallback(async (sendAlert) => {
    if (callId) {
      try {
        await api.post(`/fake-call/complete/${callId}`, {
          answered: true,
          duration_seconds: callTimer,
          send_alert: sendAlert,
        });
        if (sendAlert) {
          toast.success('Alert sent to trusted contacts');
        }
      } catch {
        toast.error('Failed to complete call');
      }
    }
    onClose?.();
  }, [callId, callTimer, onClose]);

  // Ringing screen
  if (phase === 'ringing') {
    return (
      <div className="fixed inset-0 z-[9999] flex flex-col items-center justify-between"
           style={{ background: 'linear-gradient(180deg, #0f172a 0%, #1e293b 50%, #0f172a 100%)' }}
           data-testid="fake-call-ringing-screen">
        {/* Top */}
        <div className="flex flex-col items-center pt-20">
          <div className="w-24 h-24 rounded-full bg-slate-700 flex items-center justify-center mb-4 animate-pulse shadow-lg shadow-teal-500/20">
            <span className="text-4xl font-bold text-white">{callerName[0].toUpperCase()}</span>
          </div>
          <div className="text-2xl font-bold text-white" data-testid="caller-name">{callerName}</div>
          <div className="text-sm text-slate-400 mt-1">{callerLabel}</div>
          <div className="flex items-center gap-1 mt-3">
            <Phone className="w-3.5 h-3.5 text-teal-400 animate-bounce" />
            <span className="text-teal-400 text-sm font-medium">Incoming Call...</span>
          </div>
        </div>

        {/* Action buttons */}
        <div className="flex items-center gap-16 pb-20">
          {/* Decline */}
          <div className="flex flex-col items-center gap-2">
            <button
              onClick={handleDecline}
              className="w-16 h-16 rounded-full bg-red-500 flex items-center justify-center shadow-lg shadow-red-500/30 hover:bg-red-600 active:scale-95 transition-all"
              data-testid="decline-call-btn"
            >
              <PhoneOff className="w-7 h-7 text-white" />
            </button>
            <span className="text-xs text-slate-400">Decline</span>
          </div>

          {/* Accept */}
          <div className="flex flex-col items-center gap-2">
            <button
              onClick={handleAnswer}
              className="w-16 h-16 rounded-full bg-green-500 flex items-center justify-center shadow-lg shadow-green-500/30 hover:bg-green-600 active:scale-95 transition-all animate-pulse"
              data-testid="accept-call-btn"
            >
              <Phone className="w-7 h-7 text-white" />
            </button>
            <span className="text-xs text-slate-400">Accept</span>
          </div>
        </div>
      </div>
    );
  }

  // Active call screen
  if (phase === 'active') {
    return (
      <div className="fixed inset-0 z-[9999] flex flex-col items-center justify-between"
           style={{ background: 'linear-gradient(180deg, #0f172a 0%, #1e293b 50%, #0f172a 100%)' }}
           data-testid="fake-call-active-screen">
        <div className="flex flex-col items-center pt-20">
          <div className="w-20 h-20 rounded-full bg-slate-700 flex items-center justify-center mb-4">
            <span className="text-3xl font-bold text-white">{callerName[0].toUpperCase()}</span>
          </div>
          <div className="text-xl font-bold text-white" data-testid="active-caller-name">{callerName}</div>
          <div className="text-teal-400 text-sm font-mono mt-2" data-testid="call-timer">{formatTime(callTimer)}</div>
        </div>

        <div className="flex flex-col items-center gap-8 pb-20">
          {/* Controls */}
          <div className="flex items-center gap-8">
            <button onClick={() => setMuted(!muted)}
                    className={`w-14 h-14 rounded-full flex items-center justify-center transition-all ${muted ? 'bg-white/20' : 'bg-white/10'}`}
                    data-testid="mute-btn">
              {muted ? <MicOff className="w-6 h-6 text-white" /> : <Mic className="w-6 h-6 text-white" />}
            </button>
            <button onClick={() => setSpeakerOn(!speakerOn)}
                    className={`w-14 h-14 rounded-full flex items-center justify-center transition-all ${speakerOn ? 'bg-white/20' : 'bg-white/10'}`}
                    data-testid="speaker-btn">
              {speakerOn ? <Volume2 className="w-6 h-6 text-white" /> : <VolumeX className="w-6 h-6 text-white" />}
            </button>
          </div>

          {/* End call */}
          <button
            onClick={handleEndCall}
            className="w-16 h-16 rounded-full bg-red-500 flex items-center justify-center shadow-lg shadow-red-500/30 hover:bg-red-600 active:scale-95 transition-all"
            data-testid="end-call-btn"
          >
            <PhoneOff className="w-7 h-7 text-white" />
          </button>
          <span className="text-xs text-slate-400">End Call</span>
        </div>
      </div>
    );
  }

  // Post-call screen
  if (showPostCall) {
    return (
      <div className="fixed inset-0 z-[9999] flex items-center justify-center"
           style={{ background: 'linear-gradient(180deg, #0f172a 0%, #1e293b 50%, #0f172a 100%)' }}
           data-testid="fake-call-post-screen">
        <div className="bg-slate-800 rounded-2xl p-8 mx-4 max-w-sm w-full shadow-2xl border border-slate-700">
          <div className="text-center mb-6">
            <div className="w-16 h-16 rounded-full bg-teal-600/20 flex items-center justify-center mx-auto mb-3">
              <Shield className="w-8 h-8 text-teal-400" />
            </div>
            <h2 className="text-lg font-bold text-white">Call Ended</h2>
            <p className="text-sm text-slate-400 mt-1">Duration: {formatTime(callTimer)}</p>
          </div>

          <div className="space-y-3">
            <button
              onClick={() => handlePostCallAction(true)}
              className="w-full py-3 px-4 bg-amber-500 hover:bg-amber-600 text-white rounded-xl font-bold text-sm flex items-center justify-center gap-2 transition-all active:scale-95"
              data-testid="send-alert-btn"
            >
              <Shield className="w-4 h-4" />
              Alert Trusted Contacts + Share Location
            </button>
            <button
              onClick={() => handlePostCallAction(false)}
              className="w-full py-3 px-4 bg-slate-700 hover:bg-slate-600 text-slate-300 rounded-xl font-medium text-sm flex items-center justify-center gap-2 transition-all active:scale-95"
              data-testid="dismiss-call-btn"
            >
              <X className="w-4 h-4" />
              I'm Safe — Dismiss
            </button>
          </div>
        </div>
      </div>
    );
  }

  return null;
};

export default FakeCallScreen;
