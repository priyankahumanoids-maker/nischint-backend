import React, { useEffect, useState, useCallback } from 'react';
import { MapContainer, TileLayer, Marker, Popup, useMap, Circle } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import api from '../../api';
import { X, Shield, TrendingUp, Activity, Radio, Eye, MapPin, Crosshair, AlertTriangle } from 'lucide-react';

delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon-2x.png',
  iconUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png',
});

const sosIcon = new L.DivIcon({ className: '', html: `<div style="width:24px;height:24px;border-radius:50%;background:#ef4444;border:3px solid #fff;box-shadow:0 0 12px #ef4444;animation:pulse 1.5s infinite"></div>`, iconSize: [24, 24], iconAnchor: [12, 12] });
const journeyIcon = new L.DivIcon({ className: '', html: `<div style="width:16px;height:16px;border-radius:50%;background:#3b82f6;border:2px solid #93c5fd;box-shadow:0 0 8px #3b82f6"></div>`, iconSize: [16, 16], iconAnchor: [8, 8] });
const newCriticalIcon = new L.DivIcon({ className: '', html: `<div style="width:28px;height:28px;border-radius:50%;background:#ef4444;border:3px solid #fca5a5;box-shadow:0 0 24px #ef4444,0 0 48px rgba(239,68,68,0.4);animation:newIncidentPulse 1.5s infinite"></div>`, iconSize: [28, 28], iconAnchor: [14, 14] });

// 3-tier truth-calibration model — see PRD "Live Safety Map · Truth Layer".
// Visual urgency must match data freshness so operators never over-trust
// presence-looking stale data.
//
//   live   (0–5 min)   → pulsing, full opacity, fast heartbeat
//   recent (5 min–6 h) → static colored glow, reduced opacity, no pulse
//   stale  (6 h+)      → greyed out, no pulse, "last known" only
const FRESHNESS_LIVE_MS = 5 * 60 * 1000;          // 5 min
const FRESHNESS_RECENT_MS = 6 * 60 * 60 * 1000;   // 6 h

const getFreshnessTier = (iso) => {
  if (!iso) return 'stale';
  const ms = Date.now() - new Date(iso).getTime();
  if (ms < 0) return 'live';
  if (ms <= FRESHNESS_LIVE_MS) return 'live';
  if (ms <= FRESHNESS_RECENT_MS) return 'recent';
  return 'stale';
};

// Connection-integrity state — orthogonal to freshness, computed from
// the data-pipeline heartbeat (`last_ping_at`). Prevents the silent-drift
// trap where a frozen / network-dropped device looks like the user
// "stopped moving".
//
//   LIVE_WS      ping within 60s         → pipeline healthy
//   DATA_GAP     ping in 60s–30 min      → was alive, now silent (DANGER)
//   LAST_KNOWN   no ping or > 30 min     → no live pipeline; baseline only
const PING_LIVE_MS = 60 * 1000;
const PING_GAP_MS  = 30 * 60 * 1000;

const getConnectionState = (lastPingIso) => {
  if (!lastPingIso) return 'LAST_KNOWN';
  const ms = Date.now() - new Date(lastPingIso).getTime();
  if (ms < 0) return 'LIVE_WS';
  if (ms <= PING_LIVE_MS) return 'LIVE_WS';
  if (ms <= PING_GAP_MS)  return 'DATA_GAP';
  return 'LAST_KNOWN';
};

// Final visual state — applies the 3-source reconciliation rule so an
// operator never sees a false-anxiety DATA_GAP when a fresher source of
// truth is still flowing.
//
//   Source-of-truth priority (strongest → weakest):
//     1. WebSocket live_location stream  (location_source === 'session'
//        + last_seen_at within 5 min) — proves both pipeline AND GPS are
//        flowing right now.
//     2. Backend heartbeat ping          (last_ping_at)
//     3. last_seen_at fallback           (any location origin, incl. baseline)
//
// DATA_GAP is RESERVED for the genuine anomaly: heartbeat is in the
// 60 s – 30 min "was alive, now silent" window AND there is no fresher
// live_location stream overriding it.
const getDisplayState = (lastSeenIso, lastPingIso, locationSource) => {
  // 1. Strongest signal — fresh live_location from an active session.
  //    Overrides any heartbeat-staleness DATA_GAP, because if a fresh
  //    GPS just arrived the pipeline is provably alive.
  if (
    locationSource === 'session'
    && lastSeenIso
    && (Date.now() - new Date(lastSeenIso).getTime()) <= FRESHNESS_LIVE_MS
  ) {
    return 'live';
  }

  // 2. Heartbeat reconciliation. Only flags DATA_GAP in the 60 s – 30 min
  //    window — meaning the device was alive recently but has now gone
  //    silent. No heartbeat at all → never triggers DATA_GAP, falls
  //    through to the location-freshness tier.
  const conn = getConnectionState(lastPingIso);
  if (conn === 'DATA_GAP') return 'data_gap';

  // 3. Last-known fallback — pure time-decay on the location origin.
  return getFreshnessTier(lastSeenIso);
};

// Re-exported so other Command Center surfaces (AI panel rows, popup
// metadata, future operator alerts) consume the same tier definition and
// never drift out of sync with the map.
export { getFreshnessTier, getConnectionState, getDisplayState };

const FRESHNESS_LABEL = {
  live:     { text: 'LIVE',     className: 'text-emerald-300' },
  recent:   { text: 'RECENT',   className: 'text-amber-300' },
  stale:    { text: 'STALE',    className: 'text-slate-500' },
  data_gap: { text: 'DATA GAP', className: 'text-orange-300' },
};

// Live user pin — appearance is a function of (risk_band, display_state,
// selected). Colour comes from risk band ONLY for live/recent states;
// stale pins are always grey, DATA_GAP pins are always amber, so neither
// can masquerade as a fresh urgent signal.
const buildUserIcon = (riskBand, displayState, selected) => {
  const palette = {
    CRITICAL: { core: '#ef4444', halo: 'rgba(239,68,68,0.55)' },
    HIGH:     { core: '#f97316', halo: 'rgba(249,115,22,0.55)' },
    MEDIUM:   { core: '#f59e0b', halo: 'rgba(245,158,11,0.55)' },
    MODERATE: { core: '#f59e0b', halo: 'rgba(245,158,11,0.55)' },
    LOW:      { core: '#22c55e', halo: 'rgba(34,197,94,0.55)' },
    SAFE:     { core: '#22c55e', halo: 'rgba(34,197,94,0.55)' },
  };
  const stale = { core: '#64748b', halo: 'rgba(100,116,139,0.30)' };
  const dataGap = { core: '#fb923c', halo: 'rgba(251,146,60,0.55)' };

  let c;
  if (displayState === 'data_gap') c = dataGap;
  else if (displayState === 'stale') c = stale;
  else c = palette[riskBand] || palette.LOW;

  const coreSize = selected ? 18 : 14;
  const ring = selected ? 3 : 2;

  const stateTone = {
    live:     { opacity: 1.0,  haloOpacity: 0.6,  pulse: '1.4s', glow: selected ? 18 : 10 },
    recent:   { opacity: 0.75, haloOpacity: 0.4,  pulse: null,   glow: selected ? 12 : 6 },
    stale:    { opacity: 0.40, haloOpacity: 0.0,  pulse: null,   glow: 0 },
    // Anxious fast pulse → reads as "something is wrong" without
    // imitating the calm steady pulse of a live monitored user.
    data_gap: { opacity: 0.95, haloOpacity: 0.55, pulse: '0.9s', glow: selected ? 16 : 9 },
  }[displayState] || { opacity: 0.4, haloOpacity: 0, pulse: null, glow: 0 };

  const halo = stateTone.haloOpacity > 0
    ? `<span style="position:absolute;width:${coreSize + 16}px;height:${coreSize + 16}px;border-radius:50%;background:${c.halo};opacity:${stateTone.haloOpacity};${stateTone.pulse ? `animation:userPinPulse ${stateTone.pulse} ease-in-out infinite` : ''}"></span>`
    : '';

  // Stale = dashed border ("last known"). DATA_GAP = white border + amber
  // outline ring so it reads as a *warning*, not a live state.
  let borderStyle;
  if (displayState === 'stale') borderStyle = `border:${ring}px dashed #cbd5e1`;
  else if (displayState === 'data_gap') borderStyle = `border:${ring}px solid #fff;outline:2px solid #fb923c;outline-offset:1px`;
  else borderStyle = `border:${ring}px solid #fff`;

  // DATA_GAP also stamps a small "!" glyph inside the core so even in a
  // monochrome screenshot the operator can spot the anomaly instantly.
  const glyph = displayState === 'data_gap'
    ? `<span style="position:absolute;color:#fff;font:700 ${Math.round(coreSize * 0.7)}px/1 system-ui;text-shadow:0 0 2px rgba(0,0,0,0.6);pointer-events:none">!</span>`
    : '';

  const html = `
    <div style="position:relative;width:${coreSize + 16}px;height:${coreSize + 16}px;display:flex;align-items:center;justify-content:center">
      ${halo}
      <span style="position:relative;width:${coreSize}px;height:${coreSize}px;border-radius:50%;background:${c.core};${borderStyle};box-shadow:0 0 ${stateTone.glow}px ${c.core};opacity:${stateTone.opacity};display:flex;align-items:center;justify-content:center">${glyph}</span>
    </div>`;
  return new L.DivIcon({
    className: '',
    html,
    iconSize: [coreSize + 16, coreSize + 16],
    iconAnchor: [(coreSize + 16) / 2, (coreSize + 16) / 2],
  });
};

const RISK_BAND_LABEL = (lvl) => {
  const k = (lvl || '').toString().toUpperCase();
  if (k === 'CRITICAL') return { text: 'CRITICAL', className: 'text-red-400' };
  if (k === 'HIGH') return { text: 'HIGH', className: 'text-orange-400' };
  if (k === 'MEDIUM' || k === 'MODERATE') return { text: 'MEDIUM', className: 'text-amber-400' };
  return { text: 'LOW', className: 'text-emerald-400' };
};

const relTimeShort = (iso) => {
  if (!iso) return 'unknown';
  const ms = Date.now() - new Date(iso).getTime();
  if (ms < 30000) return 'just now';
  const mins = Math.round(ms / 60000);
  if (mins < 60) return `${mins}m ago`;
  return `${Math.round(mins / 60)}h ago`;
};

const RISK_COLORS = {
  SAFE: { fill: '#22c55e', stroke: '#16a34a' },
  LOW: { fill: '#84cc16', stroke: '#65a30d' },
  MODERATE: { fill: '#f59e0b', stroke: '#d97706' },
  HIGH: { fill: '#ef4444', stroke: '#dc2626' },
  CRITICAL: { fill: '#dc2626', stroke: '#b91c1c' },
};

const SIGNAL_ICONS = {
  forecast: TrendingUp, hotspot: Radio, trend: TrendingUp,
  activity: Activity, patrol: Crosshair, environment: Eye,
  session_density: MapPin, mobility_anomaly: AlertTriangle,
};

if (typeof document !== 'undefined' && !document.getElementById('cc-map-styles')) {
  const s = document.createElement('style');
  s.id = 'cc-map-styles';
  s.textContent = `
    @keyframes newIncidentPulse{0%,100%{transform:scale(1);opacity:1}50%{transform:scale(1.6);opacity:.7}}
    @keyframes heatPulse{0%,100%{opacity:.18}50%{opacity:.35}}
    @keyframes userPinPulse{0%,100%{transform:scale(1);opacity:.55}50%{transform:scale(1.45);opacity:.15}}
    .heat-zone-critical{animation:heatPulse 2.5s ease-in-out infinite}
    .heat-zone-high{animation:heatPulse 3.5s ease-in-out infinite}
    .heat-zone-selected{stroke-dasharray:6 4!important;stroke-width:2px!important;stroke-opacity:1!important}
  `;
  document.head.appendChild(s);
}

const FitBounds = ({ markers }) => {
  const map = useMap();
  useEffect(() => {
    if (markers.length > 0) {
      map.fitBounds(L.latLngBounds(markers.map(m => [m.lat, m.lng])), { padding: [40, 40], maxZoom: 13 });
    }
  }, [markers, map]);
  return null;
};

const MapFlyTo = ({ target }) => {
  const map = useMap();
  useEffect(() => {
    if (target) map.flyTo([target.lat, target.lng], 15, { duration: 1.2 });
  }, [target, map]);
  return null;
};

/* Signal bar component */
const SignalBar = ({ signal }) => {
  const Icon = SIGNAL_ICONS[signal.key] || Activity;
  const pct = Math.min(100, (signal.score / 10) * 100);
  const color = signal.score >= 7 ? '#ef4444' : signal.score >= 4 ? '#f59e0b' : '#22c55e';
  return (
    <div className="flex items-center gap-2.5 py-1.5">
      <Icon className="w-3.5 h-3.5 text-slate-500 shrink-0" />
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between mb-0.5">
          <span className="text-[10px] text-slate-300 truncate">{signal.name}</span>
          <span className="text-[10px] font-mono" style={{ color }}>{signal.score.toFixed(1)}</span>
        </div>
        <div className="h-1 bg-slate-700/50 rounded-full overflow-hidden">
          <div className="h-full rounded-full transition-all duration-500" style={{ width: `${pct}%`, background: color }} />
        </div>
        {signal.category && <span className="text-[8px] text-slate-600">{signal.category}</span>}
        {signal.status && <span className="text-[8px] text-slate-600">{signal.status}</span>}
      </div>
      <span className="text-[9px] text-slate-600 w-8 text-right">{(signal.weight * 100).toFixed(0)}%</span>
    </div>
  );
};

/* Zone Intelligence Panel */
const ZoneIntelPanel = ({ data, onClose }) => {
  if (!data) return null;
  const rc = RISK_COLORS[data.risk_level?.toUpperCase()] || RISK_COLORS.MODERATE;
  const topSignal = data.signals?.reduce((a, b) => a.weighted > b.weighted ? a : b, { weighted: 0 });
  const recommendation = data.risk_level === 'critical' ? 'Immediate patrol deployment recommended' :
    data.risk_level === 'high' ? 'Increase caregiver presence in this zone' :
    data.risk_level === 'moderate' ? 'Monitor zone — elevated activity detected' : 'Zone within normal parameters';

  return (
    <div className="absolute top-0 right-0 bottom-0 w-[320px] z-[1001] bg-slate-900/95 backdrop-blur-md border-l border-slate-700/50 flex flex-col overflow-hidden" data-testid="zone-intel-panel">
      {/* Header */}
      <div className="px-4 py-3 border-b border-slate-700/50 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg flex items-center justify-center" style={{ background: `${rc.fill}20`, border: `1px solid ${rc.fill}40` }}>
            <Shield className="w-4 h-4" style={{ color: rc.fill }} />
          </div>
          <div>
            <h3 className="text-sm font-bold text-white">Zone Intelligence</h3>
            <p className="text-[9px] text-slate-500">{data.grid_id}</p>
          </div>
        </div>
        <button onClick={onClose} className="w-7 h-7 rounded-lg bg-slate-800 border border-slate-700/50 flex items-center justify-center text-slate-400 hover:text-white hover:bg-slate-700 transition-colors" data-testid="zone-intel-close">
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Risk Score */}
      <div className="px-4 py-3 border-b border-slate-700/30">
        <div className="flex items-center justify-between mb-2">
          <span className="text-[10px] text-slate-500 uppercase">Composite Risk</span>
          <span className="text-xs font-bold px-2 py-0.5 rounded" style={{ background: `${rc.fill}20`, color: rc.fill }}>
            {data.risk_level?.toUpperCase()}
          </span>
        </div>
        <div className="flex items-end gap-2">
          <span className="text-3xl font-bold font-mono" style={{ color: rc.fill }}>{data.composite_score?.toFixed(1)}</span>
          <span className="text-[10px] text-slate-500 mb-1">/10</span>
        </div>
        <div className="h-2 bg-slate-800 rounded-full mt-2 overflow-hidden">
          <div className="h-full rounded-full transition-all" style={{ width: `${Math.min(100, (data.composite_score / 10) * 100)}%`, background: `linear-gradient(90deg, ${rc.stroke}, ${rc.fill})` }} />
        </div>
      </div>

      {/* Location */}
      <div className="px-4 py-2 border-b border-slate-700/30 flex items-center gap-2">
        <MapPin className="w-3 h-3 text-slate-500" />
        <span className="text-[10px] text-slate-400">{data.lat?.toFixed(4)}, {data.lng?.toFixed(4)}</span>
      </div>

      {/* Signals */}
      <div className="flex-1 overflow-y-auto px-4 py-2">
        <div className="flex items-center justify-between mb-2">
          <span className="text-[10px] text-slate-500 uppercase font-medium">AI Signal Breakdown</span>
          <span className="text-[9px] text-slate-600">score / weight</span>
        </div>
        {(data.signals || []).map((sig, i) => <SignalBar key={i} signal={sig} />)}
        {topSignal?.name && (
          <div className="mt-2 px-2.5 py-1.5 rounded bg-slate-800/50 border border-slate-700/40">
            <span className="text-[9px] text-slate-500">Dominant Signal</span>
            <p className="text-[10px] text-white font-medium">{topSignal.name} ({topSignal.weighted?.toFixed(2)} weighted)</p>
          </div>
        )}
      </div>

      {/* Recommendation */}
      <div className="px-4 py-3 border-t border-slate-700/50 shrink-0">
        <span className="text-[9px] text-slate-500 uppercase">Recommended Action</span>
        <p className="text-xs text-amber-400 mt-1">{recommendation}</p>
      </div>
    </div>
  );
};

/* Heatmap zone with click handler */
const HeatmapZone = ({ zone, selected, onClick }) => {
  const rc = RISK_COLORS[zone.risk_level] || RISK_COLORS.SAFE;
  if (zone.risk_level === 'SAFE') return null;

  const radius = zone.risk_level === 'CRITICAL' ? 350 : zone.risk_level === 'HIGH' ? 280 : zone.risk_level === 'MODERATE' ? 200 : 140;
  const opacity = zone.risk_level === 'CRITICAL' ? 0.3 : zone.risk_level === 'HIGH' ? 0.22 : 0.12;
  const parts = [];
  if (zone.risk_level === 'CRITICAL') parts.push('heat-zone-critical');
  else if (zone.risk_level === 'HIGH') parts.push('heat-zone-high');
  if (selected) parts.push('heat-zone-selected');
  const cssClass = parts.join(' ') || undefined;

  return (
    <>
      <Circle center={[zone.lat, zone.lng]} radius={radius * 1.4}
        pathOptions={{ fillColor: rc.fill, fillOpacity: opacity * 0.4, color: 'transparent', className: cssClass }} />
      <Circle center={[zone.lat, zone.lng]} radius={radius}
        pathOptions={{ fillColor: rc.fill, fillOpacity: selected ? opacity * 1.8 : opacity, color: selected ? '#fff' : rc.stroke, weight: selected ? 2 : 1, opacity: selected ? 0.8 : 0.4, className: cssClass }}
        eventHandlers={{ click: () => onClick(zone) }}
      />
    </>
  );
};

export const LiveSafetyMap = ({ sosEvents = [], journeys = [], heatmapData = [], liveUsers = [], selectedUserId = null, onSelectUser, onSelectIncident, focusTarget, newIncidentIds, showHeatmap, onToggleHeatmap }) => {
  const [selectedZone, setSelectedZone] = useState(null);
  const [zoneDetail, setZoneDetail] = useState(null);
  const [loadingZone, setLoadingZone] = useState(false);
  const [, forceTick] = useState(0);

  // Re-render every 20s so freshness opacity / pulse speed visibly decay
  // even when no new pings arrive.
  useEffect(() => {
    const iv = setInterval(() => forceTick(n => n + 1), 20000);
    return () => clearInterval(iv);
  }, []);

  const handleZoneClick = useCallback(async (zone) => {
    setSelectedZone(zone.grid_id);
    setLoadingZone(true);
    try {
      const res = await api.get(`/operator/city-heatmap/cell/${zone.grid_id}`);
      setZoneDetail(res.data);
    } catch {
      setZoneDetail({ grid_id: zone.grid_id, lat: zone.lat, lng: zone.lng, composite_score: zone.risk_score || 0, risk_level: zone.risk_level?.toLowerCase(), signals: [] });
    }
    setLoadingZone(false);
  }, []);

  const closePanel = () => { setSelectedZone(null); setZoneDetail(null); };

  const allMarkers = [
    ...sosEvents.map(s => ({ lat: s.lat || 19.076, lng: s.lng || 72.877 })),
    ...journeys.map(j => ({ lat: j.location?.lat || 19.076, lng: j.location?.lng || 72.877 })),
    ...liveUsers.filter(u => u.lat != null && u.lng != null).map(u => ({ lat: u.lat, lng: u.lng })),
    ...heatmapData.filter(h => h.risk_level !== 'SAFE').slice(0, 5).map(h => ({ lat: h.lat, lng: h.lng })),
  ];
  const center = allMarkers.length > 0 ? [allMarkers[0].lat, allMarkers[0].lng] : [19.076, 72.877];
  const heatStats = {
    critical: heatmapData.filter(z => z.risk_level === 'CRITICAL').length,
    high: heatmapData.filter(z => z.risk_level === 'HIGH').length,
    moderate: heatmapData.filter(z => z.risk_level === 'MODERATE').length,
    total: heatmapData.length,
  };

  return (
    <div className="h-full w-full rounded-xl overflow-hidden border border-slate-800 relative" data-testid="cc-live-map">
      <MapContainer center={center} zoom={12} className="h-full w-full" style={{ background: '#0f172a' }} zoomControl={false} attributionControl={false}>
        <TileLayer url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png" attribution='NISCHINT' />
        {allMarkers.length > 0 && <FitBounds markers={allMarkers} />}
        <MapFlyTo target={focusTarget} />

        {heatmapData.filter(z => z.risk_level !== 'SAFE').map((zone, i) => (
          <HeatmapZone key={`heat-${i}`} zone={zone} selected={selectedZone === zone.grid_id} onClick={handleZoneClick} />
        ))}

        {/* Live monitored users — primary signal layer */}
        {liveUsers.filter(u => u.lat != null && u.lng != null).map((u) => {
          const band = (u.risk_level || 'low').toUpperCase();
          const display = getDisplayState(u.last_seen_at, u.last_ping_at, u.location_source);
          const conn = getConnectionState(u.last_ping_at);
          const selected = u.user_id === selectedUserId;
          const label = RISK_BAND_LABEL(u.risk_level);
          const fresh = FRESHNESS_LABEL[display];
          return (
            <Marker
              key={`live-user-${u.user_id}`}
              position={[u.lat, u.lng]}
              icon={buildUserIcon(band, display, selected)}
              eventHandlers={{ click: () => onSelectUser?.(u.user_id) }}
            >
              <Popup>
                <div className="text-xs" data-testid={`live-user-popup-${u.user_id}`}>
                  <div className="flex items-center justify-between gap-3 mb-0.5">
                    <p className="font-bold text-slate-900">{u.user_name || 'Unknown'}</p>
                    <span
                      className={`text-[9px] font-mono font-bold tracking-wider ${fresh.className}`}
                      data-testid={`live-user-tier-${u.user_id}`}
                    >{fresh.text}</span>
                  </div>
                  <p className={`font-mono ${label.className}`}>{label.text} · {(Number(u.final_score || 0) * 10).toFixed(1)}/10</p>
                  <p className="text-slate-600">
                    {relTimeShort(u.last_seen_at)} · {u.location_source === 'session' ? 'live session' : 'last known'}
                  </p>
                  <p className="text-[10px] text-slate-500 mt-0.5" data-testid={`live-user-conn-${u.user_id}`}>
                    Pipeline: <span className={conn === 'LIVE_WS' ? 'text-emerald-600' : conn === 'DATA_GAP' ? 'text-orange-600 font-bold' : 'text-slate-500'}>
                      {conn === 'LIVE_WS' ? 'connected' : conn === 'DATA_GAP' ? 'data gap detected' : 'not connected'}
                    </span>
                    {u.last_ping_at && conn !== 'LAST_KNOWN' && <span className="text-slate-400"> · ping {relTimeShort(u.last_ping_at)}</span>}
                  </p>
                </div>
              </Popup>
            </Marker>
          );
        })}

        {sosEvents.map((sos, i) => (
          <Marker key={`sos-${i}`} position={[sos.lat || 19.076, sos.lng || 72.877]}
            icon={newIncidentIds?.has(sos.id) ? newCriticalIcon : sosIcon}
            eventHandlers={{ click: () => onSelectIncident?.(sos) }}>
            <Popup><div className="text-xs"><p className="font-bold text-red-600">SOS Alert</p><p>{sos.senior_name || sos.user_id || 'Unknown'}</p></div></Popup>
          </Marker>
        ))}

        {journeys.map((j, i) => (
          <Marker key={`journey-${i}`} position={[j.location?.lat || 19.076, j.location?.lng || 72.877]} icon={journeyIcon}>
            <Popup><div className="text-xs"><p className="font-bold text-blue-600">Guardian Journey</p><p>Risk: {j.risk_level || 'SAFE'}</p></div></Popup>
          </Marker>
        ))}
      </MapContainer>

      {/* Controls overlay */}
      <div className="absolute top-3 right-3 z-[1000] flex flex-col gap-2" data-testid="heatmap-controls" style={{ right: zoneDetail ? '332px' : '12px', transition: 'right 0.3s ease' }}>
        <button onClick={onToggleHeatmap}
          className={`px-3 py-1.5 rounded-lg text-[10px] font-medium border backdrop-blur-md transition-all ${showHeatmap ? 'bg-red-500/20 border-red-500/40 text-red-300 hover:bg-red-500/30' : 'bg-slate-800/60 border-slate-700/50 text-slate-400 hover:bg-slate-700/60'}`}
          data-testid="heatmap-toggle">
          {showHeatmap ? 'RISK HEATMAP ON' : 'RISK HEATMAP OFF'}
        </button>
        {showHeatmap && heatStats.total > 0 && (
          <div className="bg-slate-900/80 backdrop-blur-md border border-slate-700/50 rounded-lg p-2.5 space-y-1" data-testid="heatmap-legend">
            <p className="text-[9px] text-slate-500 uppercase font-medium mb-1.5">Risk Zones</p>
            {heatStats.critical > 0 && <div className="flex items-center gap-2"><span className="w-3 h-3 rounded-full bg-red-600 heat-zone-critical" /><span className="text-[10px] text-red-400">{heatStats.critical} Critical</span></div>}
            {heatStats.high > 0 && <div className="flex items-center gap-2"><span className="w-3 h-3 rounded-full bg-red-500 heat-zone-high" /><span className="text-[10px] text-orange-400">{heatStats.high} High Risk</span></div>}
            {heatStats.moderate > 0 && <div className="flex items-center gap-2"><span className="w-3 h-3 rounded-full bg-amber-500" /><span className="text-[10px] text-amber-400">{heatStats.moderate} Moderate</span></div>}
            <p className="text-[9px] text-slate-600 pt-0.5">{heatStats.total} zones analyzed</p>
          </div>
        )}
      </div>

      {/* Loading indicator */}
      {loadingZone && (
        <div className="absolute top-1/2 right-[160px] z-[1001] -translate-y-1/2">
          <div className="w-8 h-8 border-2 border-cyan-500 border-t-transparent rounded-full animate-spin" />
        </div>
      )}

      {/* Empty-state overlay: triggers ONLY when truly nothing is on the map.
          Covers the "kid is logged in but operator sees nothing" trust gap. */}
      {liveUsers.filter(u => u.lat != null && u.lng != null).length === 0
        && journeys.length === 0
        && sosEvents.length === 0 && (
        <div
          className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-[900] px-4 py-3 rounded-lg bg-slate-900/85 backdrop-blur border border-slate-700/60 text-center pointer-events-none"
          data-testid="cc-map-empty-state"
        >
          <p className="text-[11px] font-mono text-slate-400 tracking-wider">WAITING FOR ACTIVE DEVICES…</p>
          <p className="text-[9px] text-slate-600 mt-1">No monitored users currently reporting location</p>
        </div>
      )}

      {/* Live-users state breakdown chip (bottom-left) — splits LIVE / RECENT
          / DATA-GAP / STALE so connection-integrity issues never get
          mistaken for a slow user. */}
      {liveUsers.filter(u => u.lat != null && u.lng != null).length > 0 && (() => {
        const states = { live: 0, recent: 0, stale: 0, data_gap: 0 };
        for (const u of liveUsers) {
          if (u.lat == null || u.lng == null) continue;
          states[getDisplayState(u.last_seen_at, u.last_ping_at, u.location_source)] += 1;
        }
        return (
          <div
            className="absolute bottom-3 left-3 z-[1000] px-2.5 py-1.5 rounded-lg bg-slate-900/80 backdrop-blur-md border border-slate-700/50 flex items-center gap-2.5"
            data-testid="cc-live-users-chip"
          >
            <span className="flex items-center gap-1.5" title="Pipeline connected, ping within 60s and location within 5 min">
              <span className="relative inline-flex w-2 h-2">
                {states.live > 0 && (
                  <span className="absolute inline-flex w-full h-full rounded-full bg-emerald-400 opacity-75 animate-ping" />
                )}
                <span className={`relative inline-flex w-2 h-2 rounded-full ${states.live > 0 ? 'bg-emerald-500' : 'bg-emerald-500/30'}`} />
              </span>
              <span className="text-[10px] font-mono text-emerald-300 tracking-wider" data-testid="cc-live-users-live-count">{states.live} LIVE</span>
            </span>
            <span className="text-slate-700">·</span>
            <span className="flex items-center gap-1.5" title="Pipeline ok, location 5 min – 6 h old">
              <span className={`w-2 h-2 rounded-full ${states.recent > 0 ? 'bg-amber-400' : 'bg-amber-400/30'}`} />
              <span className="text-[10px] font-mono text-amber-300 tracking-wider" data-testid="cc-live-users-recent-count">{states.recent} RECENT</span>
            </span>
            <span className="text-slate-700">·</span>
            <span className="flex items-center gap-1.5" title="Was online recently, but pipeline silent for >60s — possible disconnect">
              <span className="relative inline-flex w-2 h-2">
                {states.data_gap > 0 && (
                  <span className="absolute inline-flex w-full h-full rounded-full bg-orange-400 opacity-75 animate-ping" />
                )}
                <span className={`relative inline-flex w-2 h-2 rounded-full ${states.data_gap > 0 ? 'bg-orange-500' : 'bg-orange-500/30'}`} />
              </span>
              <span
                className={`text-[10px] font-mono tracking-wider ${states.data_gap > 0 ? 'text-orange-300 font-bold' : 'text-orange-300/60'}`}
                data-testid="cc-live-users-data-gap-count"
              >{states.data_gap} DATA-GAP</span>
            </span>
            <span className="text-slate-700">·</span>
            <span className="flex items-center gap-1.5" title="No live pipeline ever, baseline location only">
              <span className={`w-2 h-2 rounded-full ${states.stale > 0 ? 'bg-slate-500' : 'bg-slate-500/30'}`} />
              <span className="text-[10px] font-mono text-slate-400 tracking-wider" data-testid="cc-live-users-stale-count">{states.stale} STALE</span>
            </span>
          </div>
        );
      })()}

      {/* Zone Intelligence Panel */}
      <ZoneIntelPanel data={zoneDetail} onClose={closePanel} />
    </div>
  );
};
