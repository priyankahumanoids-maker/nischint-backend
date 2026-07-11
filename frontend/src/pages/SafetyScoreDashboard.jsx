import React, { useState, useCallback, useEffect, useMemo } from 'react';
import { MapContainer, TileLayer, Marker, Circle, Polyline, Popup, useMapEvents, useMap } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Input } from '../components/ui/input';
import { operatorApi } from '../api';
import { toast } from 'sonner';
import {
  Shield, MapPin, TrendingUp, TrendingDown, Minus, Loader2,
  Navigation, Share2, AlertTriangle, Clock, Route, Activity,
  Eye, Zap, Users, Star,
} from 'lucide-react';

delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon-2x.png',
  iconUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png',
});

const CAT_COLORS = {
  very_safe: '#10b981', safe: '#84cc16', moderate: '#eab308', high: '#f97316', critical: '#ef4444',
};
const CAT_BG = {
  very_safe: 'bg-emerald-500', safe: 'bg-lime-500', moderate: 'bg-amber-500', high: 'bg-orange-500', critical: 'bg-red-500',
};
const TREND_ICON = {
  rising: <TrendingUp className="w-4 h-4 text-red-500" />,
  falling: <TrendingDown className="w-4 h-4 text-emerald-500" />,
  stable: <Minus className="w-4 h-4 text-slate-400" />,
};
const SCORE_CATEGORIES = [
  [8, 'Very Safe', 'very_safe'],
  [6, 'Safe', 'safe'],
  [4, 'Moderate Risk', 'moderate'],
  [2, 'High Risk', 'high'],
  [0, 'Critical', 'critical'],
];
const SIGNAL_LABELS = {
  zone_risk: { label: 'Zone Risk', icon: MapPin, color: '#f97316' },
  dynamic_risk: { label: 'Dynamic Risk', icon: Activity, color: '#a855f7' },
  incident_density: { label: 'Incidents', icon: AlertTriangle, color: '#ef4444' },
  route_exposure: { label: 'Route Exposure', icon: Route, color: '#06b6d4' },
  time_risk: { label: 'Time Risk', icon: Clock, color: '#64748b' },
};

const mkIcon = (color) => L.divIcon({
  className: 'custom-marker',
  html: `<div style="width:28px;height:28px;border-radius:50%;background:${color};border:3px solid white;box-shadow:0 2px 8px rgba(0,0,0,0.3);display:flex;align-items:center;justify-content:center">
    <div style="width:8px;height:8px;border-radius:50%;background:white"></div></div>`,
  iconSize: [28, 28], iconAnchor: [14, 14],
});

// ── Gauge ──
const ScoreGauge = ({ score, label, category, size = 160 }) => {
  const color = CAT_COLORS[category] || '#818cf8';
  const r = (size - 20) / 2;
  const circ = 2 * Math.PI * r;
  const pct = score / 10;
  const offset = circ * (1 - pct * 0.75);

  return (
    <div className="relative flex items-center justify-center" style={{ width: size, height: size }} data-testid="score-gauge">
      <svg width={size} height={size} className="-rotate-[135deg]">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#e2e8f0"
          strokeWidth="10" strokeLinecap="round"
          strokeDasharray={`${circ * 0.75} ${circ * 0.25}`} />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color}
          strokeWidth="10" strokeLinecap="round"
          strokeDasharray={`${circ * 0.75} ${circ * 0.25}`}
          strokeDashoffset={offset}
          className="transition-all duration-1000 ease-out" />
      </svg>
      <div className="absolute text-center">
        <div className="text-3xl font-bold" style={{ color }}>{score}</div>
        <div className="text-xs text-slate-500">/ 10</div>
        <div className="text-xs font-medium mt-0.5" style={{ color }}>{label}</div>
      </div>
    </div>
  );
};

// ── Signal Breakdown ──
const SignalBreakdown = ({ signals }) => {
  if (!signals) return null;
  return (
    <div className="space-y-2" data-testid="signal-breakdown">
      {Object.entries(SIGNAL_LABELS).map(([key, cfg]) => {
        const sig = signals[key];
        if (!sig) return null;
        const Icon = cfg.icon;
        const pct = Math.min(100, sig.normalized * 100);
        return (
          <div key={key}>
            <div className="flex items-center justify-between text-xs mb-0.5">
              <span className="flex items-center gap-1.5 text-slate-600">
                <Icon className="w-3 h-3" style={{ color: cfg.color }} />{cfg.label}
              </span>
              <span className="text-slate-800 font-medium">{sig.raw}</span>
            </div>
            <div className="h-1.5 bg-slate-200 rounded-full overflow-hidden">
              <div className="h-full rounded-full transition-all duration-700" style={{
                width: `${pct}%`,
                background: pct > 70 ? '#ef4444' : pct > 50 ? '#f97316' : pct > 30 ? '#eab308' : '#22c55e',
              }} />
            </div>
          </div>
        );
      })}
    </div>
  );
};

// ── Share Card ──
const ShareCard = ({ data, type }) => {
  if (!data) return null;
  const color = CAT_COLORS[data.category] || '#818cf8';

  const handleShare = () => {
    const text = type === 'location'
      ? `Safety Score: ${data.score}/10 (${data.label}) — ${data.percentile_text}`
      : `Route Safety: ${data.score}/10 (${data.label}) — ${data.risk_zones_crossed || 0} risk zones`;
    if (navigator.share) {
      navigator.share({ title: 'NISCHINT Safety Score', text }).catch(() => {});
    } else {
      navigator.clipboard.writeText(text);
      toast.success('Score copied to clipboard');
    }
  };

  return (
    <div className="bg-gradient-to-br from-slate-800 to-slate-900 rounded-xl p-4 border border-slate-700/50" data-testid="share-card">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Shield className="w-5 h-5" style={{ color }} />
          <span className="text-sm font-bold text-white">NISCHINT</span>
        </div>
        <Button variant="ghost" size="sm" onClick={handleShare} className="text-slate-300 hover:text-white" data-testid="share-btn">
          <Share2 className="w-4 h-4" />
        </Button>
      </div>
      <div className="text-center mb-3">
        <div className="text-4xl font-bold" style={{ color }}>{data.score}</div>
        <div className="text-xs text-slate-400">out of 10</div>
        <div className="text-sm font-medium mt-1" style={{ color }}>{data.label}</div>
      </div>
      <div className="flex items-center justify-between text-xs text-slate-300 pt-2 border-t border-slate-700/50">
        <span className="flex items-center gap-1">{TREND_ICON[data.trend]} {data.trend}</span>
        <span>{data.percentile_text || `${data.percentile}th percentile`}</span>
      </div>
    </div>
  );
};

// ── Map Click Handler ──
const ClickHandler = ({ onMapClick }) => {
  useMapEvents({ click: (e) => onMapClick(e.latlng) });
  return null;
};

const FlyTo = ({ center, zoom = 14 }) => {
  const map = useMap();
  useEffect(() => { if (center) map.flyTo(center, zoom, { duration: 0.8 }); }, [center, zoom, map]);
  return null;
};

// ── Main Dashboard ──
export default function SafetyScoreDashboard() {
  const [mode, setMode] = useState('location');
  const [loading, setLoading] = useState(false);
  const [locResult, setLocResult] = useState(null);
  const [routeResult, setRouteResult] = useState(null);
  const [journeyResult, setJourneyResult] = useState(null);
  const [clickPos, setClickPos] = useState(null);
  const [origin, setOrigin] = useState({ lat: '', lng: '' });
  const [dest, setDest] = useState({ lat: '', lng: '' });
  const [sessionId, setSessionId] = useState('');
  const [mapCenter, setMapCenter] = useState([19.076, 72.877]); // Mumbai fallback
  const [mapZoom, setMapZoom] = useState(11);

  // Centre on user's actual location on first load (browser Geolocation API)
  useEffect(() => {
    if (!navigator.geolocation) return;
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setMapCenter([pos.coords.latitude, pos.coords.longitude]);
        setMapZoom(14);
      },
      (err) => {
        console.log('[SafetyScore] geolocation denied/failed, using default:', err?.message);
      },
      { enableHighAccuracy: false, timeout: 5000, maximumAge: 60000 }
    );
  }, []);

  const handleMapClick = useCallback(async (latlng) => {
    if (mode !== 'location') return;
    setClickPos(latlng);
    setLoading(true);
    try {
      const { data } = await operatorApi.getLocationScore(latlng.lat, latlng.lng);
      setLocResult(data);
      setMapCenter([latlng.lat, latlng.lng]);
      setMapZoom(14);
    } catch { toast.error('Failed to calculate score'); }
    finally { setLoading(false); }
  }, [mode]);

  const handleRouteScore = useCallback(async () => {
    if (!origin.lat || !origin.lng || !dest.lat || !dest.lng) {
      toast.error('Enter origin and destination coordinates');
      return;
    }
    setLoading(true);
    try {
      const o = { lat: parseFloat(origin.lat), lng: parseFloat(origin.lng) };
      const d = { lat: parseFloat(dest.lat), lng: parseFloat(dest.lng) };
      const { data } = await operatorApi.getRouteScore(o, d);
      setRouteResult(data);
      setMapCenter([(o.lat + d.lat) / 2, (o.lng + d.lng) / 2]);
      setMapZoom(13);
    } catch { toast.error('Failed to calculate route score'); }
    finally { setLoading(false); }
  }, [origin, dest]);

  const handleJourneyScore = useCallback(async () => {
    if (!sessionId.trim()) { toast.error('Enter session ID'); return; }
    setLoading(true);
    try {
      const { data } = await operatorApi.getJourneyScore(sessionId.trim());
      setJourneyResult(data);
    } catch (e) { toast.error(e.response?.data?.detail || 'Session not found'); }
    finally { setLoading(false); }
  }, [sessionId]);

  const activeResult = mode === 'location' ? locResult : mode === 'route' ? routeResult : journeyResult;
  const color = activeResult ? (CAT_COLORS[activeResult.category] || '#818cf8') : '#818cf8';

  return (
    <div className="space-y-4" data-testid="safety-score-dashboard">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <Star className="w-6 h-6 text-amber-500" />
          <div>
            <h1 className="text-xl font-bold text-slate-800">Safety Score</h1>
            <p className="text-xs text-slate-500">AI-powered safety intelligence for any location, route, or journey</p>
          </div>
        </div>
        <div className="flex gap-1.5 bg-white rounded-lg p-1 border border-slate-200 shadow-sm">
          {[
            { key: 'location', label: 'Location', icon: MapPin },
            { key: 'route', label: 'Route', icon: Navigation },
            { key: 'journey', label: 'Journey', icon: Shield },
          ].map(({ key, label, icon: Icon }) => (
            <button key={key} data-testid={`score-tab-${key}`}
              onClick={() => setMode(key)}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs transition-all ${
                mode === key ? 'bg-indigo-600 text-white shadow-sm' : 'text-slate-500 hover:text-slate-800 hover:bg-slate-50'
              }`}
            >
              <Icon className="w-3 h-3" />{label}
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-5 gap-4" style={{ minHeight: 500 }}>
        {/* Left Panel */}
        <div className="lg:col-span-2 space-y-4">
          {/* Mode-specific input */}
          {mode === 'location' && (
            <Card>
              <CardContent className="p-4">
                <p className="text-xs text-slate-500 mb-2">Click anywhere on the map to check safety score</p>
                {clickPos && (
                  <div className="text-[10px] text-slate-400">
                    {clickPos.lat.toFixed(5)}, {clickPos.lng.toFixed(5)}
                  </div>
                )}
              </CardContent>
            </Card>
          )}

          {mode === 'route' && (
            <Card>
              <CardContent className="p-4 space-y-3">
                <div>
                  <label className="text-[10px] text-slate-500 uppercase mb-1 block">Origin</label>
                  <div className="flex gap-2">
                    <Input placeholder="Lat" value={origin.lat} onChange={e => setOrigin(p => ({ ...p, lat: e.target.value }))}
                      className="text-xs h-8" data-testid="route-origin-lat" />
                    <Input placeholder="Lng" value={origin.lng} onChange={e => setOrigin(p => ({ ...p, lng: e.target.value }))}
                      className="text-xs h-8" data-testid="route-origin-lng" />
                  </div>
                </div>
                <div>
                  <label className="text-[10px] text-slate-500 uppercase mb-1 block">Destination</label>
                  <div className="flex gap-2">
                    <Input placeholder="Lat" value={dest.lat} onChange={e => setDest(p => ({ ...p, lat: e.target.value }))}
                      className="text-xs h-8" data-testid="route-dest-lat" />
                    <Input placeholder="Lng" value={dest.lng} onChange={e => setDest(p => ({ ...p, lng: e.target.value }))}
                      className="text-xs h-8" data-testid="route-dest-lng" />
                  </div>
                </div>
                <Button onClick={handleRouteScore} disabled={loading} size="sm"
                  className="w-full bg-indigo-600 hover:bg-indigo-700" data-testid="calc-route-score-btn">
                  {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Calculate Route Score'}
                </Button>
              </CardContent>
            </Card>
          )}

          {mode === 'journey' && (
            <Card>
              <CardContent className="p-4 space-y-3">
                <label className="text-[10px] text-slate-500 uppercase mb-1 block">Guardian Session ID</label>
                <Input placeholder="Session UUID" value={sessionId} onChange={e => setSessionId(e.target.value)}
                  className="text-xs h-8" data-testid="journey-session-id" />
                <Button onClick={handleJourneyScore} disabled={loading} size="sm"
                  className="w-full bg-indigo-600 hover:bg-indigo-700" data-testid="calc-journey-score-btn">
                  {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Calculate Journey Score'}
                </Button>
              </CardContent>
            </Card>
          )}

          {/* Score Result */}
          {activeResult && !activeResult.error && (
            <>
              <div className="flex justify-center">
                <ScoreGauge score={activeResult.score} label={activeResult.label} category={activeResult.category} />
              </div>

              {/* Metadata */}
              <Card>
                <CardContent className="p-4 space-y-3">
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-slate-500">Trend</span>
                    <span className="flex items-center gap-1 text-xs">{TREND_ICON[activeResult.trend]} <span className="capitalize text-slate-700">{activeResult.trend}</span></span>
                  </div>
                  {activeResult.percentile && (
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-slate-500">Percentile</span>
                      <span className="text-xs text-slate-700">{activeResult.percentile_text || `${activeResult.percentile}th`}</span>
                    </div>
                  )}
                  {activeResult.night_score !== undefined && (
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-slate-500">Night Score</span>
                      <span className="text-xs font-medium" style={{ color: CAT_COLORS[activeResult.night_score >= 6 ? 'safe' : activeResult.night_score >= 4 ? 'moderate' : 'high'] }}>
                        {activeResult.night_score}/10
                      </span>
                    </div>
                  )}
                  {activeResult.risk_zones_crossed !== undefined && (
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-slate-500">Risk Zones</span>
                      <span className="text-xs text-slate-700">{activeResult.risk_zones_crossed} crossed</span>
                    </div>
                  )}
                  {activeResult.max_risk && activeResult.max_risk !== 'safe' && (
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-slate-500">Max Risk</span>
                      <Badge className="text-[10px] bg-red-100 text-red-700 capitalize">{activeResult.max_risk}</Badge>
                    </div>
                  )}
                  {activeResult.alert_count !== undefined && (
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-slate-500">Alerts</span>
                      <span className="text-xs text-slate-700">{activeResult.alert_count}</span>
                    </div>
                  )}
                  {activeResult.total_penalty !== undefined && activeResult.total_penalty !== 0 && (
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-slate-500">Penalty</span>
                      <span className="text-xs text-red-600">{activeResult.total_penalty}</span>
                    </div>
                  )}
                </CardContent>
              </Card>

              {/* Signal Breakdown */}
              {activeResult.signals && (
                <Card>
                  <CardHeader className="pb-2 pt-3 px-4">
                    <CardTitle className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Signal Breakdown</CardTitle>
                  </CardHeader>
                  <CardContent className="p-4 pt-0">
                    <SignalBreakdown signals={activeResult.signals} />
                  </CardContent>
                </Card>
              )}

              {/* Journey Penalties */}
              {activeResult.penalties?.length > 0 && (
                <Card>
                  <CardHeader className="pb-2 pt-3 px-4">
                    <CardTitle className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Journey Penalties</CardTitle>
                  </CardHeader>
                  <CardContent className="p-4 pt-0 space-y-1.5">
                    {activeResult.penalties.map((p, i) => (
                      <div key={i} className="flex items-center justify-between text-xs">
                        <span className="text-slate-600">{p.reason}</span>
                        <span className="text-red-600 font-medium">{p.amount * p.count}</span>
                      </div>
                    ))}
                  </CardContent>
                </Card>
              )}

              {/* Share Card */}
              <ShareCard data={activeResult} type={mode} />
            </>
          )}

          {/* Empty state */}
          {!activeResult && !loading && (
            <div className="text-center py-8">
              <Eye className="w-8 h-8 text-slate-400 mx-auto mb-2" />
              <p className="text-sm text-slate-500">
                {mode === 'location' ? 'Click on the map to check safety' :
                 mode === 'route' ? 'Enter coordinates to score a route' :
                 'Enter a session ID to score a journey'}
              </p>
            </div>
          )}
        </div>

        {/* Right: Map */}
        <div className="lg:col-span-3 rounded-xl overflow-hidden border border-slate-200 shadow-sm" data-testid="score-map">
          <MapContainer center={mapCenter} zoom={mapZoom} style={{ height: 550, width: '100%', background: '#0f172a' }} zoomControl={false}>
            <TileLayer url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png" />
            <ClickHandler onMapClick={handleMapClick} />
            <FlyTo center={mapCenter} zoom={mapZoom} />

            {/* Location marker */}
            {clickPos && locResult && (
              <>
                <Marker position={[clickPos.lat, clickPos.lng]} icon={mkIcon(CAT_COLORS[locResult.category] || '#818cf8')}>
                  <Popup>
                    <div className="text-xs">
                      <p className="font-bold">Safety Score: {locResult.score}/10</p>
                      <p>{locResult.label}</p>
                      <p className="text-slate-500">{locResult.percentile_text}</p>
                    </div>
                  </Popup>
                </Marker>
                <Circle center={[clickPos.lat, clickPos.lng]} radius={500}
                  pathOptions={{ color: CAT_COLORS[locResult.category], fillOpacity: 0.08, weight: 1, dashArray: '4 4' }} />
              </>
            )}

            {/* Route line */}
            {routeResult && routeResult.origin && routeResult.destination && (
              <>
                <Marker position={[routeResult.origin.lat, routeResult.origin.lng]} icon={mkIcon('#22c55e')}>
                  <Popup><span className="text-xs font-bold">Origin</span></Popup>
                </Marker>
                <Marker position={[routeResult.destination.lat, routeResult.destination.lng]} icon={mkIcon('#6366f1')}>
                  <Popup><span className="text-xs font-bold">Destination</span></Popup>
                </Marker>
                <Polyline positions={[
                  [routeResult.origin.lat, routeResult.origin.lng],
                  [routeResult.destination.lat, routeResult.destination.lng],
                ]} pathOptions={{ color: CAT_COLORS[routeResult.category] || '#818cf8', weight: 3, opacity: 0.8 }} />
              </>
            )}
          </MapContainer>
        </div>
      </div>

      {/* Score Legend */}
      <Card>
        <CardContent className="p-3">
          <div className="flex items-center gap-4 flex-wrap justify-center" data-testid="score-legend">
            {SCORE_CATEGORIES.map(([threshold, label, key]) => (
              <div key={key} className="flex items-center gap-1.5 text-xs">
                <div className="w-3 h-3 rounded-full" style={{ background: CAT_COLORS[key] }} />
                <span className="text-slate-600">{label}</span>
                <span className="text-slate-400">({threshold}-{threshold === 0 ? 2 : threshold + 2})</span>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
