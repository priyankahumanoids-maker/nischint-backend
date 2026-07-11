import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../../api';
import { Play, MapPin, Navigation, Loader2, ArrowLeft, Footprints, Car, Train } from 'lucide-react';

const MODES = [
  { id: 'walking', icon: Footprints, label: 'Walk' },
  { id: 'driving', icon: Car, label: 'Drive' },
  { id: 'transit', icon: Train, label: 'Transit' },
];

export default function MobileSession() {
  const navigate = useNavigate();
  const [destName, setDestName] = useState('');
  const [destLat, setDestLat] = useState('');
  const [destLng, setDestLng] = useState('');
  const [mode, setMode] = useState('walking');
  const [loading, setLoading] = useState(false);
  const [checkingSession, setCheckingSession] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const res = await api.get('/safety-events/session-status');
        if (res.data.tracking_active) {
          navigate('/m/live', { replace: true });
          return;
        }
      } catch { /* ignore */ }
      setCheckingSession(false);
    })();
  }, [navigate]);

  const handleStart = async () => {
    setLoading(true);
    try {
      const destination = destName ? {
        name: destName,
        lat: destLat ? parseFloat(destLat) : null,
        lng: destLng ? parseFloat(destLng) : null,
      } : null;

      const res = await api.post('/safety-events/start-session', {
        destination,
        mode,
      });

      if (res.data.status === 'started' || res.data.status === 'already_active') {
        navigate('/m/live');
      }
    } catch (e) {
      console.error('Failed to start session:', e);
    }
    setLoading(false);
  };

  if (checkingSession) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="w-8 h-8 text-teal-400 animate-spin" />
      </div>
    );
  }

  return (
    <div className="px-4 pt-4 pb-6" data-testid="mobile-session">
      <button onClick={() => navigate('/m/home')} className="p-2 -ml-2 rounded-full active:bg-slate-800" data-testid="session-back-btn">
        <ArrowLeft className="w-5 h-5 text-slate-400" />
      </button>

      <div className="mt-4 text-center mb-6">
        <div className="w-14 h-14 rounded-full bg-teal-500/15 flex items-center justify-center mx-auto mb-3">
          <Navigation className="w-6 h-6 text-teal-400" />
        </div>
        <h1 className="text-lg font-bold text-white">Start Safety Session</h1>
        <p className="text-sm text-slate-400 mt-1">AI will monitor your journey in real-time</p>
      </div>

      {/* Destination */}
      <div className="space-y-3 mb-6">
        <div>
          <label className="text-[11px] text-slate-500 uppercase font-medium mb-1.5 block">Destination Name</label>
          <div className="relative">
            <MapPin className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
            <input
              type="text"
              value={destName}
              onChange={e => setDestName(e.target.value)}
              placeholder="e.g. Home, School, Office..."
              className="w-full pl-10 pr-4 py-3 rounded-xl bg-slate-800 border border-slate-700 text-white text-sm placeholder:text-slate-600 focus:border-teal-500/50 focus:outline-none"
              data-testid="dest-name-input"
            />
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-[11px] text-slate-500 uppercase font-medium mb-1.5 block">Latitude</label>
            <input
              type="number"
              step="any"
              value={destLat}
              onChange={e => setDestLat(e.target.value)}
              placeholder="28.6139"
              className="w-full px-3 py-3 rounded-xl bg-slate-800 border border-slate-700 text-white text-sm placeholder:text-slate-600 focus:border-teal-500/50 focus:outline-none"
              data-testid="dest-lat-input"
            />
          </div>
          <div>
            <label className="text-[11px] text-slate-500 uppercase font-medium mb-1.5 block">Longitude</label>
            <input
              type="number"
              step="any"
              value={destLng}
              onChange={e => setDestLng(e.target.value)}
              placeholder="77.2090"
              className="w-full px-3 py-3 rounded-xl bg-slate-800 border border-slate-700 text-white text-sm placeholder:text-slate-600 focus:border-teal-500/50 focus:outline-none"
              data-testid="dest-lng-input"
            />
          </div>
        </div>
      </div>

      {/* Travel Mode */}
      <div className="mb-8">
        <label className="text-[11px] text-slate-500 uppercase font-medium mb-2 block">Travel Mode</label>
        <div className="flex gap-2">
          {MODES.map(({ id, icon: Icon, label }) => (
            <button
              key={id}
              onClick={() => setMode(id)}
              className={`flex-1 py-3 rounded-xl flex flex-col items-center gap-1.5 transition-all ${
                mode === id
                  ? 'bg-teal-500/15 border border-teal-500/40 text-teal-400'
                  : 'bg-slate-800 border border-slate-700 text-slate-500'
              }`}
              data-testid={`mode-${id}`}
            >
              <Icon className="w-5 h-5" />
              <span className="text-[11px] font-medium">{label}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Start Button */}
      <button
        onClick={handleStart}
        disabled={loading}
        className="w-full py-4 rounded-2xl bg-teal-500 text-white font-bold text-sm flex items-center justify-center gap-2 active:scale-[0.98] transition-transform disabled:opacity-50 shadow-lg shadow-teal-500/20"
        data-testid="start-session-btn"
      >
        {loading ? (
          <><Loader2 className="w-5 h-5 animate-spin" /> Starting...</>
        ) : (
          <><Play className="w-5 h-5" /> Start Tracking</>
        )}
      </button>

      <p className="text-center text-[10px] text-slate-600 mt-3">
        Guardian AI will continuously analyze your safety during this session
      </p>
    </div>
  );
}
