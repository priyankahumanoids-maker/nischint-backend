import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../../api';
import {
  Navigation, MapPin, Shield, Loader2, ArrowLeft,
  AlertTriangle, CheckCircle, Route,
} from 'lucide-react';

const SAFETY_COLORS = {
  high: { bg: 'bg-emerald-500/10', border: 'border-emerald-500/30', text: 'text-emerald-400', badge: 'bg-emerald-500' },
  medium: { bg: 'bg-amber-500/10', border: 'border-amber-500/30', text: 'text-amber-400', badge: 'bg-amber-500' },
  low: { bg: 'bg-red-500/10', border: 'border-red-500/30', text: 'text-red-400', badge: 'bg-red-500' },
};

function getSafetyTier(score) {
  if (score >= 7) return 'high';
  if (score >= 4) return 'medium';
  return 'low';
}

export default function MobileSafeRoute() {
  const navigate = useNavigate();
  const [originLat, setOriginLat] = useState('');
  const [originLng, setOriginLng] = useState('');
  const [destLat, setDestLat] = useState('');
  const [destLng, setDestLng] = useState('');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [locating, setLocating] = useState(false);

  const useCurrentLocation = async () => {
    setLocating(true);
    try {
      const pos = await new Promise((resolve, reject) =>
        navigator.geolocation.getCurrentPosition(resolve, reject, { timeout: 8000 })
      );
      setOriginLat(pos.coords.latitude.toFixed(6));
      setOriginLng(pos.coords.longitude.toFixed(6));
    } catch {
      alert('Could not get location');
    }
    setLocating(false);
  };

  const analyze = async () => {
    if (!originLat || !originLng || !destLat || !destLng) return;
    setLoading(true);
    try {
      const res = await api.post('/safety-events/safe-route', {
        origin_lat: parseFloat(originLat),
        origin_lng: parseFloat(originLng),
        dest_lat: parseFloat(destLat),
        dest_lng: parseFloat(destLng),
      });
      setResult(res.data);
    } catch {
      setResult({ error: true });
    }
    setLoading(false);
  };

  return (
    <div className="px-4 pt-4 pb-6" data-testid="mobile-safe-route">
      <button onClick={() => navigate(-1)} className="p-2 -ml-2 rounded-full active:bg-slate-800" data-testid="safe-route-back-btn">
        <ArrowLeft className="w-5 h-5 text-slate-400" />
      </button>

      <div className="mt-3 text-center mb-5">
        <Navigation className="w-8 h-8 text-blue-400 mx-auto mb-2" />
        <h1 className="text-lg font-bold text-white">Safe Route Analysis</h1>
        <p className="text-sm text-slate-400 mt-1">AI assesses route safety before you travel</p>
      </div>

      {/* Origin */}
      <div className="space-y-2 mb-4">
        <div className="flex items-center justify-between">
          <label className="text-[11px] text-slate-500 uppercase font-medium">Origin</label>
          <button
            onClick={useCurrentLocation}
            disabled={locating}
            className="text-[10px] text-teal-400 font-medium flex items-center gap-1"
            data-testid="use-location-btn"
          >
            {locating ? <Loader2 className="w-3 h-3 animate-spin" /> : <MapPin className="w-3 h-3" />}
            Use My Location
          </button>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <input type="number" step="any" value={originLat} onChange={e => setOriginLat(e.target.value)} placeholder="Lat" className="px-3 py-2.5 rounded-xl bg-slate-800 border border-slate-700 text-white text-sm placeholder:text-slate-600 focus:border-blue-500/50 focus:outline-none" data-testid="origin-lat" />
          <input type="number" step="any" value={originLng} onChange={e => setOriginLng(e.target.value)} placeholder="Lng" className="px-3 py-2.5 rounded-xl bg-slate-800 border border-slate-700 text-white text-sm placeholder:text-slate-600 focus:border-blue-500/50 focus:outline-none" data-testid="origin-lng" />
        </div>
      </div>

      {/* Destination */}
      <div className="space-y-2 mb-6">
        <label className="text-[11px] text-slate-500 uppercase font-medium">Destination</label>
        <div className="grid grid-cols-2 gap-2">
          <input type="number" step="any" value={destLat} onChange={e => setDestLat(e.target.value)} placeholder="Lat" className="px-3 py-2.5 rounded-xl bg-slate-800 border border-slate-700 text-white text-sm placeholder:text-slate-600 focus:border-blue-500/50 focus:outline-none" data-testid="dest-lat" />
          <input type="number" step="any" value={destLng} onChange={e => setDestLng(e.target.value)} placeholder="Lng" className="px-3 py-2.5 rounded-xl bg-slate-800 border border-slate-700 text-white text-sm placeholder:text-slate-600 focus:border-blue-500/50 focus:outline-none" data-testid="dest-lng" />
        </div>
      </div>

      {/* Analyze Button */}
      <button
        onClick={analyze}
        disabled={loading || !originLat || !destLat}
        className="w-full py-3.5 rounded-2xl bg-blue-500 text-white font-bold text-sm flex items-center justify-center gap-2 active:scale-[0.98] transition-transform disabled:opacity-50 mb-6"
        data-testid="analyze-route-btn"
      >
        {loading ? (
          <><Loader2 className="w-4 h-4 animate-spin" /> Analyzing...</>
        ) : (
          <><Route className="w-4 h-4" /> Analyze Route Safety</>
        )}
      </button>

      {/* Results */}
      {result && !result.error && (
        <div className="space-y-3" data-testid="route-results">
          {(result.routes || []).map((route, i) => {
            const safety = (route.safety_score || route.score || 5);
            const tier = getSafetyTier(safety);
            const s = SAFETY_COLORS[tier];
            const isRecommended = i === 0 || route.recommended;

            return (
              <div
                key={i}
                className={`p-4 rounded-2xl ${s.bg} border ${s.border} ${isRecommended ? 'ring-1 ring-offset-1 ring-offset-slate-950 ring-blue-500/30' : ''}`}
                data-testid={`route-card-${i}`}
              >
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <Shield className={`w-4 h-4 ${s.text}`} />
                    <span className="text-xs font-semibold text-white">
                      Route {String.fromCharCode(65 + i)}
                    </span>
                    {isRecommended && (
                      <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-blue-500/20 text-blue-400 font-bold">RECOMMENDED</span>
                    )}
                  </div>
                  <div className={`px-2 py-0.5 rounded-full ${s.badge} text-white text-[10px] font-bold`}>
                    {safety.toFixed(1)}/10
                  </div>
                </div>

                <div className="flex items-center gap-4 text-[10px] text-slate-400">
                  {route.distance_km && <span>{route.distance_km.toFixed(1)} km</span>}
                  {route.duration_min && <span>{Math.round(route.duration_min)} min</span>}
                </div>

                {route.factors && (
                  <div className="mt-2 space-y-1">
                    {Object.entries(route.factors).slice(0, 3).map(([key, val]) => (
                      <div key={key} className="flex items-center gap-2">
                        <span className="text-[9px] text-slate-500 w-20 truncate capitalize">{key.replace(/_/g, ' ')}</span>
                        <div className="flex-1 h-1 rounded-full bg-slate-700">
                          <div className="h-1 rounded-full bg-slate-400" style={{ width: `${(val || 0) * 100}%` }} />
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}

          {result.recommendation && (
            <div className="p-3 rounded-xl bg-blue-500/10 border border-blue-500/20 flex items-start gap-2">
              <CheckCircle className="w-4 h-4 text-blue-400 mt-0.5 shrink-0" />
              <p className="text-[11px] text-blue-300 leading-relaxed">{result.recommendation}</p>
            </div>
          )}
        </div>
      )}

      {result?.error && (
        <div className="p-4 rounded-2xl bg-red-500/10 border border-red-500/30 text-center" data-testid="route-error">
          <AlertTriangle className="w-6 h-6 text-red-400 mx-auto mb-2" />
          <p className="text-xs text-red-400">Could not analyze route. Please check coordinates.</p>
        </div>
      )}
    </div>
  );
}
