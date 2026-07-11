import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import api from '../api';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import {
  Radio, AlertTriangle, Users, CheckCircle, Loader2, Shield, MapPin,
  Clock, ExternalLink, UserCheck, RefreshCw, ArrowUpCircle, Bell, BellRing,
  Volume2, VolumeX, Play,
} from 'lucide-react';
import { toast } from 'sonner';
import { MapContainer, TileLayer, Marker, Popup, useMap } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';

delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon-2x.png',
  iconUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png',
});

const sosIcon = new L.DivIcon({ className: '', html: `<div style="width:20px;height:20px;border-radius:50%;background:#ef4444;border:2px solid #fff;box-shadow:0 0 10px #ef4444;animation:pulse 1.5s infinite"></div>`, iconSize: [20, 20], iconAnchor: [10, 10] });
const newCriticalIcon = new L.DivIcon({ className: '', html: `<div style="width:24px;height:24px;border-radius:50%;background:#ef4444;border:3px solid #fca5a5;box-shadow:0 0 20px #ef4444,0 0 40px rgba(239,68,68,0.4);animation:newIncidentPulse 1.5s infinite"></div>`, iconSize: [24, 24], iconAnchor: [12, 12] });
const alertIcon = new L.DivIcon({ className: '', html: `<div style="width:16px;height:16px;border-radius:50%;background:#f59e0b;border:2px solid #fde68a"></div>`, iconSize: [16, 16], iconAnchor: [8, 8] });
const cgIcon = new L.DivIcon({ className: '', html: `<div style="width:14px;height:14px;border-radius:50%;background:#22c55e;border:2px solid #86efac"></div>`, iconSize: [14, 14], iconAnchor: [7, 7] });

const SEV = { critical: 'bg-red-500/15 text-red-400 border-red-500/30', high: 'bg-orange-500/15 text-orange-400 border-orange-500/30', medium: 'bg-amber-500/15 text-amber-400 border-amber-500/30', low: 'bg-slate-500/15 text-slate-400 border-slate-500/30' };
const STATUS_COLORS = { open: 'bg-red-500/20 text-red-400', in_progress: 'bg-blue-500/20 text-blue-400', resolved: 'bg-emerald-500/20 text-emerald-400', assigned: 'bg-amber-500/20 text-amber-400' };

/* ── Alert CSS injected once ── */
const alertStyleId = 'op-alert-styles';
if (typeof document !== 'undefined' && !document.getElementById(alertStyleId)) {
  const style = document.createElement('style');
  style.id = alertStyleId;
  style.textContent = `
    @keyframes headerAlertFlash {
      0%   { background-color: #0f172a; box-shadow: inset 0 0 0 0 transparent; }
      25%  { background-color: #7f1d1d; box-shadow: inset 0 -2px 20px rgba(239,68,68,0.4); }
      50%  { background-color: #450a0a; box-shadow: inset 0 -2px 30px rgba(239,68,68,0.6); }
      75%  { background-color: #7f1d1d; box-shadow: inset 0 -2px 20px rgba(239,68,68,0.4); }
      100% { background-color: #0f172a; box-shadow: inset 0 0 0 0 transparent; }
    }
    .header-alert-flash {
      animation: headerAlertFlash 0.8s ease-in-out 4;
    }
    @keyframes criticalPulse {
      0%, 100% { opacity: 1; transform: scale(1); }
      50% { opacity: 0.6; transform: scale(1.15); }
    }
    .critical-pulse { animation: criticalPulse 1.2s ease-in-out infinite; }
    @keyframes sosPing {
      0% { box-shadow: 0 0 0 0 rgba(239,68,68,0.7); }
      100% { box-shadow: 0 0 0 12px rgba(239,68,68,0); }
    }
    .sos-ping { animation: sosPing 1.5s ease-out infinite; }
    @keyframes newIncidentPulse {
      0%   { transform: scale(1);   opacity: 1; }
      50%  { transform: scale(1.6); opacity: 0.7; }
      100% { transform: scale(1);   opacity: 1; }
    }
  `;
  document.head.appendChild(style);
}

/* ── Map auto-focus component ── */
const MapFlyTo = ({ target }) => {
  const map = useMap();
  useEffect(() => {
    if (target) {
      map.flyTo([target.lat, target.lng], 15, { duration: 1.2 });
    }
  }, [target, map]);
  return null;
};

/* ── Header with flash + alert badge ── */
const OperatorHeader = ({ metrics, onRefresh, refreshing, flashing, newCriticalCount, alertsMuted, onToggleMute }) => (
  <div
    id="operator-header"
    className={`bg-slate-900 border-b border-slate-700/50 px-6 flex items-center justify-between ${flashing ? 'header-alert-flash' : ''}`}
    data-testid="operator-header"
  >
    <div className="flex items-center gap-3">
      <div className="w-9 h-9 rounded-lg bg-orange-500/20 flex items-center justify-center border border-orange-500/30">
        <Shield className="w-5 h-5 text-orange-400" />
      </div>
      <div>
        <h1 className="text-base font-bold text-white">Operator Dashboard</h1>
        <span className="text-[10px] text-slate-400">Incident Operations</span>
      </div>
      {newCriticalCount > 0 && (
        <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-red-600/30 border border-red-500/50 critical-pulse" data-testid="new-critical-badge">
          <BellRing className="w-3.5 h-3.5 text-red-400" />
          <span className="text-[10px] font-bold text-red-300">{newCriticalCount} NEW CRITICAL</span>
        </div>
      )}
    </div>
    <div className="flex items-center gap-3">
      {[
        { label: 'Active SOS', value: metrics?.active_sos || 0, color: 'red' },
        { label: 'New Alerts', value: metrics?.new_alerts || 0, color: 'amber' },
        { label: 'Assigned', value: metrics?.assigned || 0, color: 'blue' },
        { label: 'Resolved', value: metrics?.resolved_today || 0, color: 'emerald' },
        { label: 'Caregivers', value: metrics?.caregivers_online || 0, color: 'green' },
      ].map(s => (
        <div key={s.label} className={`px-3 py-1.5 rounded-lg bg-${s.color}-500/10 border border-${s.color}-500/20`} data-testid={`op-stat-${s.label.toLowerCase().replace(/\s/g,'-')}`}>
          <p className="text-[9px] text-slate-500 uppercase">{s.label}</p>
          <p className={`text-lg font-bold text-${s.color}-400 leading-tight`}>{s.value}</p>
        </div>
      ))}
      <Button size="sm" variant="ghost" className="text-slate-400 h-8 w-8 p-0" onClick={onToggleMute} data-testid="toggle-mute" title={alertsMuted ? 'Unmute alerts' : 'Mute alerts'}>
        {alertsMuted ? <VolumeX className="w-4 h-4 text-red-400" /> : <Volume2 className="w-4 h-4" />}
      </Button>
      <Button size="sm" variant="ghost" className="text-slate-400" onClick={onRefresh} data-testid="op-refresh">
        <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin' : ''}`} />
      </Button>
    </div>
  </div>
);

/* ── Incident Queue ── */
const IncidentQueue = ({ incidents, filter, setFilter, onSelect, selectedId }) => (
  <div className="bg-slate-800/40 rounded-lg border border-slate-700/50 flex flex-col h-full" data-testid="incident-queue">
    <div className="px-3 py-2 border-b border-slate-700/50 flex items-center justify-between shrink-0">
      <h3 className="text-sm font-semibold text-white flex items-center gap-1.5"><Radio className="w-3.5 h-3.5 text-red-400" />Incidents</h3>
      <span className="text-[10px] bg-slate-700/50 text-slate-400 px-2 py-0.5 rounded-full">{incidents.length}</span>
    </div>
    <div className="flex gap-1 px-2 pt-2">
      {['all', 'critical', 'open', 'assigned', 'resolved'].map(f => (
        <button key={f} onClick={() => setFilter(f)} className={`text-[9px] px-2 py-1 rounded ${filter === f ? 'bg-teal-500/20 text-teal-400' : 'text-slate-500 hover:text-slate-300'}`}>{f}</button>
      ))}
    </div>
    <div className="flex-1 overflow-y-auto p-2 space-y-1.5">
      {incidents.length === 0 ? <p className="text-xs text-slate-500 text-center py-6">No incidents</p> : incidents.map(inc => (
        <button key={inc.id} onClick={() => onSelect(inc)} className={`w-full text-left p-2.5 rounded-lg border transition-all ${selectedId === inc.id ? 'border-teal-500/50 bg-teal-500/10' : 'border-slate-700/30 bg-slate-800/30 hover:border-slate-600'} ${inc._isNew ? 'ring-1 ring-red-500/50' : ''}`} data-testid={`incident-item-${inc.id}`}>
          <div className="flex items-center justify-between mb-1">
            <div className="flex items-center gap-1">
              {inc._isNew && <span className="w-1.5 h-1.5 rounded-full bg-red-500 sos-ping" />}
              <Badge className={`text-[9px] px-1.5 py-0 border ${SEV[inc.severity] || SEV.low}`}>{inc.severity}</Badge>
            </div>
            <span className="text-[9px] text-slate-500">{inc.created_at ? new Date(inc.created_at).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}) : ''}</span>
          </div>
          <p className="text-xs text-slate-300 truncate">{inc.senior_name || inc.device_identifier || 'Unknown'}</p>
          <div className="flex items-center justify-between mt-1">
            <span className="text-[9px] text-slate-500">{inc.incident_type?.replace('_',' ')}</span>
            <Badge className={`text-[8px] px-1 py-0 ${STATUS_COLORS[inc.status] || STATUS_COLORS.open}`}>{inc.status}</Badge>
          </div>
        </button>
      ))}
    </div>
  </div>
);

/* ── Dispatch Panel ── */
const DispatchPanel = ({ incident, caregivers, onAssign, onResolve, onEscalate }) => {
  const [aiRisk, setAiRisk] = useState(null);

  useEffect(() => {
    const userId = incident?.user_id || incident?.senior_id;
    if (!userId) { setAiRisk(null); return; }
    api.get(`/guardian-ai/${userId}/risk-score`)
      .then(r => setAiRisk(r.data))
      .catch(() => setAiRisk(null));
  }, [incident?.user_id, incident?.senior_id]);

  if (!incident) return (
    <div className="bg-slate-800/40 rounded-lg border border-slate-700/50 flex items-center justify-center h-full" data-testid="dispatch-panel-empty">
      <p className="text-xs text-slate-500">Select an incident to dispatch</p>
    </div>
  );

  const riskColor = aiRisk?.risk_level === 'critical' ? 'red' : aiRisk?.risk_level === 'high' ? 'orange' : aiRisk?.risk_level === 'moderate' ? 'amber' : 'emerald';

  return (
    <div className="bg-slate-800/40 rounded-lg border border-slate-700/50 flex flex-col h-full" data-testid="dispatch-panel">
      <div className="px-4 py-3 border-b border-slate-700/50 shrink-0">
        <div className="flex items-center justify-between mb-1">
          <Badge className={`text-[10px] border ${SEV[incident.severity] || SEV.low}`}>{incident.severity} - {incident.incident_type?.replace('_',' ')}</Badge>
          <Badge className={`text-[10px] ${STATUS_COLORS[incident.status] || STATUS_COLORS.open}`}>{incident.status}</Badge>
        </div>
        <p className="text-sm font-medium text-white">{incident.senior_name || 'Unknown User'}</p>
        <p className="text-[10px] text-slate-400">{incident.created_at ? new Date(incident.created_at).toLocaleString() : ''}</p>
      </div>
      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        {/* AI Risk Intelligence */}
        {aiRisk && (
          <div className={`p-2.5 rounded-lg border border-${riskColor}-500/30 bg-${riskColor}-500/5`} data-testid="ai-risk-panel">
            <div className="flex items-center justify-between mb-2">
              <span className="text-[9px] uppercase text-slate-500 font-medium">AI Risk Score</span>
              <span className={`text-lg font-bold font-mono text-${riskColor}-400`}>{(aiRisk.final_score * 10).toFixed(1)}</span>
            </div>
            <Badge className={`text-[9px] mb-2 bg-${riskColor}-500/15 text-${riskColor}-400`}>{aiRisk.risk_level?.toUpperCase()}</Badge>
            {aiRisk.top_factors?.length > 0 && (
              <div className="mt-1.5 space-y-1">
                <p className="text-[9px] text-slate-500">Why flagged:</p>
                {aiRisk.top_factors.map((f, i) => (
                  <div key={i} className="flex items-start gap-1.5">
                    <span className={`w-1 h-1 rounded-full bg-${riskColor}-400 mt-1.5 shrink-0`} />
                    <span className="text-[10px] text-slate-300">{f.description}</span>
                  </div>
                ))}
              </div>
            )}
            <div className="mt-2 pt-1.5 border-t border-slate-700/30">
              <p className="text-[9px] text-slate-500">Recommended</p>
              <p className="text-[10px] text-amber-400">{aiRisk.action_detail}</p>
            </div>
          </div>
        )}
        <div>
          <p className="text-[10px] uppercase text-slate-500 mb-1.5">Assign Caregiver</p>
          <div className="space-y-1">
            {caregivers.length === 0 ? <p className="text-xs text-slate-500">No caregivers available</p> :
              caregivers.map(cg => (
                <div key={cg.id} className="flex items-center justify-between p-2 rounded bg-slate-700/30 border border-slate-700/50">
                  <div>
                    <p className="text-xs text-slate-300">{cg.full_name}</p>
                    <span className={`text-[9px] ${cg.status === 'available' ? 'text-emerald-400' : 'text-amber-400'}`}>{cg.status}</span>
                  </div>
                  <Button size="sm" className="h-6 text-[10px]" disabled={cg.status === 'busy' || incident.status === 'resolved'} onClick={() => onAssign(incident.id, cg.id)} data-testid={`assign-cg-${cg.id}`}>
                    <UserCheck className="w-3 h-3 mr-1" />Assign
                  </Button>
                </div>
              ))
            }
          </div>
        </div>
      </div>
      <div className="p-3 border-t border-slate-700/50 flex flex-wrap gap-2 shrink-0">
        <Button size="sm" className="h-7 text-[10px] bg-emerald-600 hover:bg-emerald-700" onClick={() => onResolve(incident.id)} disabled={incident.status === 'resolved'} data-testid="resolve-incident">
          <CheckCircle className="w-3 h-3 mr-1" />Resolve
        </Button>
        <Button size="sm" variant="outline" className="h-7 text-[10px] border-red-500/30 text-red-400 hover:bg-red-500/10" onClick={() => onEscalate(incident.id)} data-testid="escalate-incident">
          <ArrowUpCircle className="w-3 h-3 mr-1" />Escalate
        </Button>
      </div>
    </div>
  );
};

/* ── Active Caregivers ── */
const ActiveCaregivers = ({ caregivers }) => (
  <div className="bg-slate-800/40 rounded-lg border border-slate-700/50 flex flex-col h-full" data-testid="active-caregivers">
    <div className="px-3 py-2 border-b border-slate-700/50 flex items-center gap-1.5 shrink-0">
      <Users className="w-3.5 h-3.5 text-emerald-400" />
      <h3 className="text-sm font-semibold text-white">Caregivers</h3>
    </div>
    <div className="flex-1 overflow-y-auto p-2 space-y-1">
      {caregivers.map(cg => (
        <div key={cg.id} className="flex items-center justify-between p-2 rounded bg-slate-700/20 border border-slate-700/40">
          <div>
            <p className="text-xs text-slate-300">{cg.full_name}</p>
            <span className={`text-[9px] ${cg.status === 'available' ? 'text-emerald-400' : cg.status === 'busy' ? 'text-amber-400' : 'text-slate-500'}`}>{cg.status}</span>
          </div>
          {cg.current_assignment_id && <Badge className="text-[8px] bg-amber-500/20 text-amber-400">Assigned</Badge>}
        </div>
      ))}
      {caregivers.length === 0 && <p className="text-xs text-slate-500 text-center py-3">No caregivers online</p>}
    </div>
  </div>
);

/* ── Incident Timeline ── */
const IncidentTimeline = ({ incident }) => {
  if (!incident) return (
    <div className="bg-slate-800/40 rounded-lg border border-slate-700/50 flex items-center justify-center h-full" data-testid="incident-timeline-empty">
      <p className="text-xs text-slate-500">Select incident for timeline</p>
    </div>
  );
  const events = [
    { time: incident.created_at, label: `${incident.incident_type?.replace('_',' ')} triggered`, color: 'red' },
    incident.acknowledged_at && { time: incident.acknowledged_at, label: 'Acknowledged', color: 'blue' },
    incident.assigned_at && { time: incident.assigned_at, label: 'Caregiver assigned', color: 'amber' },
    incident.resolved_at && { time: incident.resolved_at, label: 'Resolved', color: 'emerald' },
  ].filter(Boolean).sort((a, b) => new Date(a.time) - new Date(b.time));

  return (
    <div className="bg-slate-800/40 rounded-lg border border-slate-700/50 flex flex-col h-full" data-testid="incident-timeline">
      <div className="px-3 py-2 border-b border-slate-700/50 flex items-center gap-1.5 shrink-0">
        <Clock className="w-3.5 h-3.5 text-blue-400" />
        <h3 className="text-sm font-semibold text-white">Timeline</h3>
      </div>
      <div className="flex-1 overflow-y-auto p-3 space-y-2">
        {events.map((ev, i) => (
          <div key={i} className="flex items-start gap-2">
            <span className={`w-2 h-2 rounded-full bg-${ev.color}-500 mt-1.5 shrink-0`} />
            <div>
              <p className="text-xs text-slate-300">{ev.label}</p>
              <p className="text-[9px] text-slate-500">{new Date(ev.time).toLocaleTimeString()}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

/* ── Quick Actions ── */
const QuickActions = ({ navigate }) => (
  <div className="bg-slate-800/40 rounded-lg border border-slate-700/50 flex flex-col h-full" data-testid="quick-actions">
    <div className="px-3 py-2 border-b border-slate-700/50 shrink-0">
      <h3 className="text-sm font-semibold text-white">Quick Actions</h3>
    </div>
    <div className="p-3 space-y-1.5 flex-1">
      {[
        { label: 'Journey Replay', icon: Play, onClick: () => navigate('/replay') },
        { label: 'Command Center', icon: ExternalLink, onClick: () => navigate('/command-center') },
        { label: 'Admin Panel', icon: Shield, onClick: () => navigate('/admin') },
        { label: 'Dashboard', icon: MapPin, onClick: () => navigate('/family') },
      ].map(a => (
        <button key={a.label} onClick={a.onClick} className="w-full flex items-center gap-2 px-3 py-2 rounded bg-slate-700/30 hover:bg-slate-700/50 border border-slate-700/40 text-xs text-slate-300 transition-colors" data-testid={`qa-${a.label.toLowerCase().replace(/\s/g,'-')}`}>
          <a.icon className="w-3.5 h-3.5 text-slate-400" />{a.label}
        </button>
      ))}
    </div>
  </div>
);

/* ═════════════════════════════════════════════════════════════
   MAIN OPERATOR DASHBOARD — with real-time alert system
   ═════════════════════════════════════════════════════════════ */
export default function OperatorDashboard() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [metrics, setMetrics] = useState(null);
  const [incidents, setIncidents] = useState([]);
  const [caregivers, setCaregivers] = useState([]);
  const [selectedIncident, setSelectedIncident] = useState(null);
  const [filter, setFilter] = useState('all');
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  // Alert system state
  const [headerFlashing, setHeaderFlashing] = useState(false);
  const [newCriticalCount, setNewCriticalCount] = useState(0);
  const [alertsMuted, setAlertsMuted] = useState(false);
  const [mapFocusTarget, setMapFocusTarget] = useState(null);
  const previousIdsRef = useRef(new Set());
  const alertAudioRef = useRef(null);
  const isFirstLoadRef = useRef(true);

  const isAuthorized = user?.role === 'admin' || user?.role === 'operator' || user?.roles?.includes('admin') || user?.roles?.includes('operator');

  // Initialize audio + request notification permission
  useEffect(() => {
    alertAudioRef.current = new Audio('/sounds/alert.wav');
    alertAudioRef.current.volume = 0.7;

    if ('Notification' in window && Notification.permission === 'default') {
      Notification.requestPermission();
    }
  }, []);

  // Play alert sound
  const playAlert = useCallback(() => {
    if (alertsMuted || !alertAudioRef.current) return;
    alertAudioRef.current.currentTime = 0;
    alertAudioRef.current.play().catch(() => {});
  }, [alertsMuted]);

  // Show browser notification
  const showBrowserNotification = useCallback((incident) => {
    if ('Notification' in window && Notification.permission === 'granted') {
      new Notification('CRITICAL INCIDENT', {
        body: `${incident.senior_name || 'Unknown'} — ${incident.incident_type?.replace('_', ' ')}`,
        icon: '/favicon.ico',
        tag: `incident-${incident.id}`,
        requireInteraction: true,
      });
    }
  }, []);

  // Flash header
  const flashHeader = useCallback(() => {
    setHeaderFlashing(true);
    setTimeout(() => setHeaderFlashing(false), 3500);
  }, []);

  // Trigger full alert sequence
  const triggerAlert = useCallback((newCriticals) => {
    playAlert();
    flashHeader();
    setNewCriticalCount(newCriticals.length);
    // Auto-select first new critical incident → dispatch panel opens instantly
    if (newCriticals[0]) {
      setSelectedIncident(newCriticals[0]);
      setMapFocusTarget({
        lat: 19.076 + (Math.random() - 0.5) * 0.04,
        lng: 72.877 + (Math.random() - 0.5) * 0.04,
      });
      showBrowserNotification(newCriticals[0]);
    }
    setTimeout(() => setNewCriticalCount(0), 10000);
  }, [playAlert, flashHeader, showBrowserNotification]);

  const fetchData = useCallback(async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true);
    try {
      const [mRes, iRes, cgRes] = await Promise.all([
        api.get('/operator/dashboard/metrics').catch(() => null),
        api.get('/operator/incidents?limit=50').catch(() => null),
        api.get('/operator/dashboard/caregivers').catch(() => null),
      ]);
      if (mRes?.data) setMetrics(mRes.data);
      if (cgRes?.data) setCaregivers(cgRes.data.caregivers || []);

      if (iRes?.data) {
        const incoming = iRes.data.incidents || iRes.data || [];
        const prevIds = previousIdsRef.current;

        // Detect new critical incidents (skip first load)
        if (!isFirstLoadRef.current && prevIds.size > 0) {
          const newCriticals = incoming.filter(
            i => i.severity === 'critical' && i.status === 'open' && !prevIds.has(i.id)
          );
          if (newCriticals.length > 0) {
            triggerAlert(newCriticals);
            // Mark new incidents for visual highlighting
            const newIds = new Set(newCriticals.map(i => i.id));
            incoming.forEach(i => { i._isNew = newIds.has(i.id); });
            // Clear _isNew after 8s
            setTimeout(() => {
              setIncidents(prev => prev.map(i => ({ ...i, _isNew: false })));
            }, 8000);
          }
        }
        isFirstLoadRef.current = false;

        // Update tracked IDs
        previousIdsRef.current = new Set(incoming.map(i => i.id));
        setIncidents(incoming);
      }
    } catch { /* silent */ }
    setLoading(false);
    setRefreshing(false);
  }, [triggerAlert]);

  useEffect(() => {
    if (!isAuthorized) { navigate('/family'); return; }
    fetchData();
  }, [isAuthorized, navigate, fetchData]);

  useEffect(() => { const iv = setInterval(() => fetchData(true), 15000); return () => clearInterval(iv); }, [fetchData]);

  const filteredIncidents = incidents.filter(i => {
    if (filter === 'all') return true;
    if (filter === 'critical') return i.severity === 'critical';
    if (filter === 'assigned') return i.assigned_to_user_id;
    return i.status === filter;
  });

  const handleAssign = async (incidentId, caregiverId) => {
    try {
      await api.post(`/operator/incidents/${incidentId}/assign?caregiver_id=${caregiverId}`);
      toast.success('Caregiver assigned');
      fetchData(true);
    } catch { toast.error('Assignment failed'); }
  };
  const handleResolve = async (id) => {
    try {
      await api.patch(`/operator/incidents/${id}/status?new_status=resolved`);
      toast.success('Incident resolved');
      fetchData(true);
    } catch { toast.error('Failed to resolve'); }
  };
  const handleEscalate = async (id) => {
    try {
      await api.post(`/operator/incidents/${id}/escalate`);
      toast.success('Escalated');
      fetchData(true);
    } catch { toast.error('Escalation failed'); }
  };

  if (!isAuthorized) return null;
  if (loading) return (
    <div className="h-screen bg-slate-900 flex items-center justify-center">
      <Loader2 className="w-8 h-8 animate-spin text-orange-500" />
    </div>
  );

  const mapIncidents = filteredIncidents.filter(i => i.severity === 'critical' || i.incident_type === 'sos').map(i => ({
    ...i, lat: 19.076 + (Math.random() - 0.5) * 0.05, lng: 72.877 + (Math.random() - 0.5) * 0.05,
  }));

  return (
    <div className="h-screen bg-slate-900 text-white grid grid-rows-[68px_1fr_220px] overflow-hidden" data-testid="operator-dashboard">
      <OperatorHeader
        metrics={metrics}
        onRefresh={() => fetchData(true)}
        refreshing={refreshing}
        flashing={headerFlashing}
        newCriticalCount={newCriticalCount}
        alertsMuted={alertsMuted}
        onToggleMute={() => setAlertsMuted(m => !m)}
      />

      {/* Middle Row */}
      <div className="grid grid-cols-[340px_1fr_340px] gap-3 p-3 min-h-0">
        <IncidentQueue incidents={filteredIncidents} filter={filter} setFilter={setFilter} onSelect={setSelectedIncident} selectedId={selectedIncident?.id} />

        {/* Live Map */}
        <div className="rounded-lg overflow-hidden border border-slate-700/50" data-testid="operator-map">
          <MapContainer center={[19.076, 72.877]} zoom={12} className="h-full w-full" style={{ background: '#0f172a' }} zoomControl={false} attributionControl={false}>
            <TileLayer url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png" />
            <MapFlyTo target={mapFocusTarget} />
            {mapIncidents.map((inc, i) => (
              <Marker key={i} position={[inc.lat, inc.lng]} icon={inc._isNew ? newCriticalIcon : inc.severity === 'critical' ? sosIcon : alertIcon}>
                <Popup><div className="text-xs"><p className="font-bold">{inc.incident_type}</p><p>{inc.senior_name}</p></div></Popup>
              </Marker>
            ))}
            {caregivers.filter(c => c.status !== 'offline').map((cg, i) => (
              <Marker key={`cg-${i}`} position={[19.076 + (Math.random()-0.5)*0.03, 72.877 + (Math.random()-0.5)*0.03]} icon={cgIcon}>
                <Popup><div className="text-xs"><p className="font-bold text-emerald-600">{cg.full_name}</p><p>{cg.status}</p></div></Popup>
              </Marker>
            ))}
          </MapContainer>
        </div>

        <DispatchPanel incident={selectedIncident} caregivers={caregivers} onAssign={handleAssign} onResolve={handleResolve} onEscalate={handleEscalate} />
      </div>

      {/* Bottom Row */}
      <div className="grid grid-cols-3 gap-3 px-3 pb-3 min-h-0">
        <ActiveCaregivers caregivers={caregivers} />
        <IncidentTimeline incident={selectedIncident} />
        <QuickActions navigate={navigate} />
      </div>
    </div>
  );
}
