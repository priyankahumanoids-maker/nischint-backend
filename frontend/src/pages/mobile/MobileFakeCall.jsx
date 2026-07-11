import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../../api';
import { Phone, PhoneCall, X, Loader2 } from 'lucide-react';

export default function MobileFakeCall() {
  const navigate = useNavigate();
  const [phase, setPhase] = useState('setup'); // setup | ringing | answered | ended
  const [callerName, setCallerName] = useState('Mom');
  const [delay, setDelay] = useState(3);
  const ringRef = useRef(null);

  const presets = ['Mom', 'Dad', 'Boss', 'Partner', 'Friend'];

  const trigger = async () => {
    // Log to backend (non-blocking)
    api.post('/safety-events/fake-call', { caller_name: callerName, delay_seconds: delay }).catch(() => {});

    // Start local fake call after delay
    setPhase('waiting');
    setTimeout(() => {
      setPhase('ringing');
      if (navigator.vibrate) {
        ringRef.current = setInterval(() => navigator.vibrate([300, 200, 300]), 1000);
      }
    }, delay * 1000);
  };

  const answer = () => {
    clearInterval(ringRef.current);
    if (navigator.vibrate) navigator.vibrate(50);
    setPhase('answered');
  };

  const hangUp = () => {
    clearInterval(ringRef.current);
    setPhase('ended');
    setTimeout(() => navigate(-1), 500);
  };

  useEffect(() => () => clearInterval(ringRef.current), []);

  if (phase === 'ringing' || phase === 'answered') {
    return (
      <div className="fixed inset-0 z-[9999] bg-gradient-to-b from-slate-900 to-slate-950 flex flex-col items-center justify-between py-16 px-6" data-testid="fake-call-screen">
        <div className="text-center mt-10">
          <div className={`w-20 h-20 rounded-full ${phase === 'ringing' ? 'bg-green-500/20 animate-pulse' : 'bg-teal-500/20'} flex items-center justify-center mx-auto mb-4`}>
            <PhoneCall className={`w-8 h-8 ${phase === 'ringing' ? 'text-green-400' : 'text-teal-400'}`} />
          </div>
          <p className="text-2xl font-bold text-white">{callerName}</p>
          <p className="text-sm text-slate-400 mt-1">
            {phase === 'ringing' ? 'Incoming call...' : 'Connected'}
          </p>
        </div>

        <div className="flex items-center gap-8">
          {phase === 'ringing' ? (
            <>
              <button onClick={hangUp} className="w-16 h-16 rounded-full bg-red-500 flex items-center justify-center shadow-lg active:scale-90 transition-transform" data-testid="decline-btn">
                <Phone className="w-7 h-7 text-white rotate-[135deg]" />
              </button>
              <button onClick={answer} className="w-16 h-16 rounded-full bg-green-500 flex items-center justify-center shadow-lg active:scale-90 transition-transform" data-testid="answer-btn">
                <Phone className="w-7 h-7 text-white" />
              </button>
            </>
          ) : (
            <button onClick={hangUp} className="w-16 h-16 rounded-full bg-red-500 flex items-center justify-center shadow-lg active:scale-90 transition-transform" data-testid="hangup-btn">
              <Phone className="w-7 h-7 text-white rotate-[135deg]" />
            </button>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="px-4 pt-4 pb-6" data-testid="mobile-fake-call">
      <button onClick={() => navigate(-1)} className="p-2 -ml-2 rounded-full active:bg-slate-800">
        <X className="w-5 h-5 text-slate-400" />
      </button>

      <div className="mt-4 text-center mb-6">
        <Phone className="w-8 h-8 text-purple-400 mx-auto mb-2" />
        <h1 className="text-lg font-bold text-white">Fake Call</h1>
        <p className="text-sm text-slate-400">Simulate an incoming call to escape a situation</p>
      </div>

      {/* Caller presets */}
      <div className="mb-6">
        <p className="text-xs text-slate-500 uppercase mb-2">Caller Name</p>
        <div className="flex flex-wrap gap-2">
          {presets.map(name => (
            <button
              key={name}
              onClick={() => setCallerName(name)}
              className={`px-4 py-2 rounded-full text-xs font-medium transition-all ${
                callerName === name
                  ? 'bg-purple-500 text-white'
                  : 'bg-slate-800 text-slate-400 border border-slate-700'
              }`}
            >
              {name}
            </button>
          ))}
        </div>
        <input
          type="text"
          value={callerName}
          onChange={e => setCallerName(e.target.value)}
          className="mt-2 w-full px-4 py-2.5 rounded-xl bg-slate-800 border border-slate-700 text-white text-sm"
          placeholder="Custom name..."
          data-testid="caller-name-input"
        />
      </div>

      {/* Delay */}
      <div className="mb-8">
        <p className="text-xs text-slate-500 uppercase mb-2">Ring in {delay} seconds</p>
        <input
          type="range" min="0" max="30" value={delay}
          onChange={e => setDelay(Number(e.target.value))}
          className="w-full accent-purple-500"
        />
      </div>

      {/* Trigger */}
      <button
        onClick={trigger}
        disabled={phase === 'waiting'}
        className="w-full py-3.5 rounded-2xl bg-purple-500 text-white font-bold text-sm flex items-center justify-center gap-2 active:scale-[0.98] transition-transform disabled:opacity-50"
        data-testid="trigger-fake-call-btn"
      >
        {phase === 'waiting' ? (
          <><Loader2 className="w-4 h-4 animate-spin" /> Calling in {delay}s...</>
        ) : (
          <><PhoneCall className="w-4 h-4" /> Start Fake Call</>
        )}
      </button>
    </div>
  );
}
