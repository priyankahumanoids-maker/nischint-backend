import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Routes, Route, NavLink, useNavigate } from 'react-router-dom';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { 
  Shield, Home, Bell, Settings, Users, Smartphone,
  AlertTriangle, CheckCircle, XCircle, LogOut, Loader2,
  Activity, RefreshCw, Wifi, WifiOff, Clock, Timer,
  Mail, MessageSquare, Zap, Send, SkullIcon, RotateCcw, PauseCircle,
  UserPlus, Link as LinkIcon, Eye, Star, Map, Navigation, Brain, Phone, BellRing, ShieldAlert, Mic,
  BarChart3
} from 'lucide-react';
import GuardianSafetyDashboard from './GuardianSafetyDashboard';
import SafetyScoreDashboard from './SafetyScoreDashboard';
import GuardianMetrics from '../components/dashboard/GuardianMetrics';
import EmergencyMap from '../components/EmergencyMap';
import RouteMonitorPage from './RouteMonitorPage';
import SafetyBrainDashboard from './SafetyBrainDashboard';
import FakeCallPage from './FakeCallPage';
import FakeNotificationPage from './FakeNotificationPage';
import SOSPage from './SOSPage';
import GuardianAIPage from './GuardianAIPage';
import VoiceTriggerPage from './VoiceTriggerPage';
import SafetyZonesPage from './SafetyZonesPage';
import FamilyLivePage from './FamilyLivePage';
import FakeCallScreen from '../components/FakeCallScreen';
import NotificationOverlay from '../components/NotificationOverlay';
import { useAuth } from '../contexts/AuthContext';
import { dashboardApi, incidentsApi, seniorsApi, devicesApi, createEventSource } from '../api';
import { toast } from 'sonner';
import { requestPushToken, onForegroundMessage } from '../lib/firebase';
import api from '../api';
import DeviceStatusBadge from '../components/DeviceStatusBadge';
import DeviceHealthCard from '../components/DeviceHealthCard';
import { formatRelativeTime } from '../utils/time';

// SSE Connection Status Component
// Module-scoped dedup set for `risk_update` SSE events. Survives
// component re-mounts so a reconnect that replays events can't
// double-apply them. Bounded LRU-style in the handler.
const _seenRiskEmitKeys = new Set();

const ConnectionStatus = ({ connected }) => (
  <div className={`flex items-center gap-2 px-3 py-1 rounded-full text-xs ${connected ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>
    {connected ? <Wifi className="w-3 h-3" /> : <WifiOff className="w-3 h-3" />}
    {connected ? 'Live' : 'Disconnected'}
  </div>
);

const Sidebar = ({ onLogout, connected, user }) => {
  const navigate = useNavigate();
  return (
  <aside className="w-64 bg-slate-900 text-white min-h-screen p-6 flex flex-col">
    <div className="flex items-center gap-3 mb-4">
      <div className="w-10 h-10 bg-teal-500 rounded-lg flex items-center justify-center">
        <Shield className="w-6 h-6" />
      </div>
      <div>
        <h1 className="font-bold text-lg">NISCHINT</h1>
        <p className="text-xs text-slate-400">Family Dashboard</p>
      </div>
    </div>
    
    <div className="mb-6">
      <ConnectionStatus connected={connected} />
    </div>

    <nav className="flex-1 space-y-2">
      {/* ─── PRIMARY (single screen) ─── */}
      <NavLink
        to="/family"
        end
        className={({ isActive }) =>
          `flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${
            isActive ? 'bg-teal-600 text-white' : 'text-slate-400 hover:bg-slate-800'
          }`
        }
        data-testid="nav-overview"
      >
        <Home className="w-5 h-5" />
        Overview
      </NavLink>
      <NavLink
        to="/family/live"
        className={({ isActive }) =>
          `flex items-center gap-3 px-4 py-3 rounded-lg transition-all ${
            isActive ? 'bg-teal-600 text-white shadow' : 'text-white bg-gradient-to-r from-teal-700/40 to-teal-600/20 hover:from-teal-600 hover:to-teal-500 border border-teal-500/30'
          }`
        }
        data-testid="nav-live-care"
      >
        <Shield className="w-5 h-5" />
        <div className="flex flex-col items-start leading-tight">
          <span className="font-semibold">Live Care</span>
          <span className="text-[10px] opacity-75">Map · Status · Zones · Score</span>
        </div>
      </NavLink>

      {/* ─── CARE TOOLS ─── */}
      <p className="px-4 pt-3 pb-1 text-[10px] uppercase tracking-wider text-slate-500 font-bold">Care Tools</p>
      <NavLink
        to="/family/safety-brain"
        className={({ isActive }) =>
          `flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${
            isActive ? 'bg-teal-600 text-white' : 'text-slate-400 hover:bg-slate-800'
          }`
        }
        data-testid="nav-safety-brain"
      >
        <Brain className="w-5 h-5" />
        Safety Brain
      </NavLink>
      <NavLink
        to="/family/escape-call"
        className={({ isActive }) =>
          `flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${
            isActive ? 'bg-teal-600 text-white' : 'text-slate-400 hover:bg-slate-800'
          }`
        }
        data-testid="nav-escape-call"
      >
        <Phone className="w-5 h-5" />
        Escape Call
      </NavLink>
      <NavLink
        to="/family/escape-notification"
        className={({ isActive }) =>
          `flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${
            isActive ? 'bg-teal-600 text-white' : 'text-slate-400 hover:bg-slate-800'
          }`
        }
        data-testid="nav-escape-notification"
      >
        <BellRing className="w-5 h-5" />
        Escape Notification
      </NavLink>
      <NavLink
        to="/family/sos"
        className={({ isActive }) =>
          `flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${
            isActive ? 'bg-red-600 text-white' : 'text-slate-400 hover:bg-slate-800'
          }`
        }
        data-testid="nav-sos"
      >
        <ShieldAlert className="w-5 h-5" />
        Silent SOS
      </NavLink>
      <NavLink
        to="/family/guardian-ai"
        className={({ isActive }) =>
          `flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${
            isActive ? 'bg-teal-600 text-white' : 'text-slate-400 hover:bg-slate-800'
          }`
        }
        data-testid="nav-guardian-ai"
      >
        <Brain className="w-5 h-5" />
        Guardian AI
      </NavLink>
      <NavLink
        to="/family/voice-trigger"
        className={({ isActive }) =>
          `flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${
            isActive ? 'bg-teal-600 text-white' : 'text-slate-400 hover:bg-slate-800'
          }`
        }
        data-testid="nav-voice-trigger"
      >
        <Mic className="w-5 h-5" />
        Voice Trigger
      </NavLink>
      <NavLink
        to="/family/incidents"
        className={({ isActive }) =>
          `flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${
            isActive ? 'bg-teal-600 text-white' : 'text-slate-400 hover:bg-slate-800'
          }`
        }
        data-testid="nav-incidents"
      >
        <Bell className="w-5 h-5" />
        Incidents
      </NavLink>
      <NavLink
        to="/family/metrics"
        className={({ isActive }) =>
          `flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${
            isActive ? 'bg-teal-600 text-white' : 'text-slate-400 hover:bg-slate-800'
          }`
        }
        data-testid="nav-metrics"
      >
        <BarChart3 className="w-5 h-5" />
        Response Metrics
      </NavLink>

      {/* ─── CONFIGURATION ─── */}
      <p className="px-4 pt-3 pb-1 text-[10px] uppercase tracking-wider text-slate-500 font-bold">Configuration</p>
      <NavLink
        to="/family/seniors"
        className={({ isActive }) =>
          `flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${
            isActive ? 'bg-teal-600 text-white' : 'text-slate-400 hover:bg-slate-800'
          }`
        }
        data-testid="nav-seniors"
      >
        <Users className="w-5 h-5" />
        Protected Users
      </NavLink>
      <NavLink
        to="/family/safety-zones"
        className={({ isActive }) =>
          `flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${
            isActive ? 'bg-teal-600 text-white' : 'text-slate-400 hover:bg-slate-800'
          }`
        }
        data-testid="nav-safety-zones"
      >
        <Map className="w-5 h-5" />
        Safety Zones
      </NavLink>
      <NavLink 
        to="/family/settings" 
        className={({ isActive }) => 
          `flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${
            isActive ? 'bg-teal-600 text-white' : 'text-slate-400 hover:bg-slate-800'
          }`
        }
        data-testid="nav-settings"
      >
        <Settings className="w-5 h-5" />
        Settings
      </NavLink>
    </nav>

    <div className="pt-6 border-t border-slate-700">
      <div className="flex items-center gap-3 mb-4">
        <div className="w-8 h-8 bg-teal-600 rounded-full flex items-center justify-center text-sm font-bold">
          {(user?.full_name || user?.email || 'G')[0].toUpperCase()}
        </div>
        <div className="overflow-hidden">
          <p className="font-medium text-sm truncate" data-testid="user-display-name">{user?.full_name || user?.email || 'Guardian'}</p>
          {user?.full_name && <p className="text-xs text-slate-400 truncate">{user?.email}</p>}
          {user?.roles?.includes('admin') && <Badge className="text-xs bg-red-500/20 text-red-300 border-red-500/30 mt-0.5">Admin</Badge>}
        </div>
      </div>
      {user?.roles?.includes('admin') && (
        <Button 
          variant="ghost" 
          className="w-full justify-start text-red-300 hover:text-white hover:bg-red-600/20 mb-2"
          onClick={() => navigate('/admin')}
          data-testid="admin-panel-btn"
        >
          <Shield className="w-5 h-5 mr-3" />
          Admin Panel
        </Button>
      )}
      <Button 
        variant="ghost" 
        className="w-full justify-start text-slate-400 hover:text-white"
        onClick={onLogout}
        data-testid="logout-btn"
      >
        <LogOut className="w-5 h-5 mr-3" />
        Sign Out
      </Button>
    </div>
  </aside>
  );
};

const formatSeconds = (seconds) => {
  if (!seconds) return "-";
  const minutes = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${minutes}m ${secs}s`;
};

// Role-specific badge for Protected User cards — 🎒 Kids, 🛡️ Women, 👵 Elderly
const KIND_BADGE_CONFIG = {
  child:    { emoji: '🎒', label: 'Kids Safety',   className: 'bg-sky-100 text-sky-700 border-sky-200' },
  kid:      { emoji: '🎒', label: 'Kids Safety',   className: 'bg-sky-100 text-sky-700 border-sky-200' },
  woman:    { emoji: '🛡️', label: 'Women Safety',  className: 'bg-rose-100 text-rose-700 border-rose-200' },
  senior:   { emoji: '👵', label: 'Elderly Care',  className: 'bg-amber-100 text-amber-700 border-amber-200' },
  parent:   { emoji: '💙', label: 'Family',        className: 'bg-emerald-100 text-emerald-700 border-emerald-200' },
  guardian: { emoji: '💙', label: 'Family',        className: 'bg-emerald-100 text-emerald-700 border-emerald-200' },
};

const KindBadge = ({ kind, size = 'sm', testId }) => {
  const key = (kind || 'senior').toString().toLowerCase();
  const cfg = KIND_BADGE_CONFIG[key] || { emoji: '👤', label: 'Protected', className: 'bg-slate-100 text-slate-700 border-slate-200' };
  const padding = size === 'xs' ? 'px-1.5 py-0.5 text-[10px]' : 'px-2 py-0.5 text-xs';
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border font-semibold ${padding} ${cfg.className}`}
      data-testid={testId || `kind-badge-${key}`}
    >
      <span aria-hidden="true">{cfg.emoji}</span>
      <span>{cfg.label}</span>
    </span>
  );
};

const Overview = () => {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [summary, setSummary] = useState(null);
  const [sla, setSla] = useState(null);
  const [loading, setLoading] = useState(true);
  const [drillDown, setDrillDown] = useState(null); // {type, title, data, loading}
  const [drillDownData, setDrillDownData] = useState([]);
  const [drillDownLoading, setDrillDownLoading] = useState(false);

  const fetchSummary = async () => {
    try {
      const [summaryData, slaData] = await Promise.all([
        dashboardApi.getSummary(),
        api.get('/dashboard/sla').then(r => r.data),
      ]);
      setSummary(summaryData);
      setSla(slaData);
    } catch (error) {
      toast.error('Failed to load dashboard data');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSummary();
    const interval = setInterval(fetchSummary, 10000);
    return () => clearInterval(interval);
  }, []);

  const toIST = (ts) => {
    if (!ts) return '--';
    try {
      const d = new Date(ts);
      if (isNaN(d.getTime())) return '--';
      return d.toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', hour12: true, day: 'numeric', month: 'short' });
    } catch { return '--'; }
  };

  const openDrillDown = async (type) => {
    setDrillDown(type);
    setDrillDownLoading(true);
    setDrillDownData([]);
    try {
      if (type === 'protected-users') {
        const res = await api.get('/dashboard/family-users');
        setDrillDownData(res.data || []);
      } else if (type === 'devices') {
        const res = await api.get('/dashboard/family-devices');
        setDrillDownData(res.data || []);
      } else if (type === 'active-incidents') {
        const data = await incidentsApi.getIncidents(user.id, 'open');
        setDrillDownData(data || []);
      } else if (type === 'critical') {
        const data = await incidentsApi.getIncidents(user.id, 'open');
        setDrillDownData((data || []).filter(i => i.severity === 'critical'));
      } else if (type === 'online') {
        const res = await api.get('/dashboard/family-devices');
        setDrillDownData((res.data || []).filter(d => d.status === 'online'));
      } else if (type === 'offline') {
        const res = await api.get('/dashboard/family-devices');
        setDrillDownData((res.data || []).filter(d => d.status !== 'online'));
      }
    } catch (e) {
      toast.error('Failed to load data');
    }
    setDrillDownLoading(false);
  };

  const handleAcknowledge = async (incidentId) => {
    try {
      await incidentsApi.acknowledge(incidentId);
      toast.success('Incident acknowledged');
      openDrillDown(drillDown);
    } catch { toast.error('Failed to acknowledge'); }
  };

  const handleBulkAcknowledge = async () => {
    for (const inc of drillDownData) {
      if (inc.status === 'open') {
        try { await incidentsApi.acknowledge(inc.id); } catch {}
      }
    }
    toast.success('All incidents acknowledged');
    openDrillDown(drillDown);
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-8 h-8 animate-spin text-teal-600" />
      </div>
    );
  }

  const statCards = [
    { type: 'protected-users', icon: Users, value: summary?.total_seniors || 0, label: 'Protected Users', gradient: 'from-blue-500 to-blue-600', muted: 'text-blue-100' },
    { type: 'devices', icon: Smartphone, value: summary?.total_devices || 0, label: 'Devices', gradient: 'from-purple-500 to-purple-600', muted: 'text-purple-100' },
    { type: 'active-incidents', icon: Bell, value: summary?.active_incidents || 0, label: 'Active Incidents', gradient: 'from-amber-500 to-amber-600', muted: 'text-amber-100' },
    { type: 'critical', icon: AlertTriangle, value: summary?.critical_incidents || 0, label: 'Critical', gradient: 'from-red-500 to-red-600', muted: 'text-red-100' },
    { type: 'online', icon: CheckCircle, value: summary?.devices_online || 0, label: 'Online', gradient: 'from-green-500 to-green-600', muted: 'text-green-100' },
    { type: 'offline', icon: XCircle, value: summary?.devices_offline || 0, label: 'Offline', gradient: 'from-slate-500 to-slate-600', muted: 'text-slate-300' },
  ];

  return (
    <div className="space-y-6" data-testid="family-overview">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold text-slate-800">Dashboard Overview</h2>
        <Button variant="outline" size="sm" onClick={fetchSummary} data-testid="refresh-btn">
          <RefreshCw className="w-4 h-4 mr-2" />
          Refresh
        </Button>
      </div>

      {/* Clickable Stat Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-6 gap-4">
        {statCards.map((card) => {
          const Icon = card.icon;
          return (
            <Card
              key={card.type}
              className={`bg-gradient-to-br ${card.gradient} text-white border-0 cursor-pointer transition-all duration-200 hover:shadow-lg hover:shadow-${card.gradient.split('-')[1]}-500/30 hover:scale-[1.03]`}
              onClick={() => openDrillDown(card.type)}
              data-testid={`stat-card-${card.type}`}
            >
              <CardContent className="p-6">
                <div className="flex flex-col">
                  <Icon className="w-8 h-8 mb-2 opacity-80" />
                  <p className="text-3xl font-bold">{card.value}</p>
                  <p className={`text-sm ${card.muted}`}>{card.label}</p>
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>

      {/* Drill-Down Panel */}
      {drillDown && (
        <Card className="border-2 border-teal-200 shadow-lg animate-in slide-in-from-top-2" data-testid="drill-down-panel">
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-lg">
                {drillDown === 'protected-users' && 'Protected Users'}
                {drillDown === 'devices' && 'All Devices'}
                {drillDown === 'active-incidents' && 'Active Incidents'}
                {drillDown === 'critical' && 'Critical Incidents'}
                {drillDown === 'online' && 'Online Users'}
                {drillDown === 'offline' && 'Offline Users'}
              </CardTitle>
              <div className="flex gap-2">
                {(drillDown === 'active-incidents' || drillDown === 'critical') && drillDownData.length > 0 && (
                  <Button size="sm" variant="outline" onClick={handleBulkAcknowledge} data-testid="bulk-ack-btn">
                    <CheckCircle className="w-4 h-4 mr-1" /> Acknowledge All
                  </Button>
                )}
                <Button size="sm" variant="ghost" onClick={() => setDrillDown(null)} data-testid="close-drill-down">
                  <XCircle className="w-4 h-4" />
                </Button>
              </div>
            </div>
          </CardHeader>
          <CardContent>
            {drillDownLoading ? (
              <div className="flex items-center justify-center py-8"><Loader2 className="w-6 h-6 animate-spin text-teal-500" /></div>
            ) : drillDownData.length === 0 ? (
              <p className="text-slate-500 text-center py-6">No data found</p>
            ) : (
              <div className="space-y-2 max-h-[400px] overflow-y-auto">
                {/* Protected Users */}
                {drillDown === 'protected-users' && drillDownData.map((s, i) => {
                  const kind = (s.kind || s.role || 'senior').toLowerCase();
                  const iconBg = kind === 'child' || kind === 'kid' ? 'bg-sky-100 text-sky-600'
                    : kind === 'woman' ? 'bg-rose-100 text-rose-600'
                    : kind === 'senior' ? 'bg-amber-100 text-amber-600'
                    : 'bg-blue-100 text-blue-600';
                  return (
                  <div key={s.id || i} className="flex items-center justify-between p-3 bg-slate-50 rounded-lg hover:bg-slate-100 transition-colors" data-testid={`user-row-${i}`}>
                    <div className="flex items-center gap-3 min-w-0">
                      <div className={`w-9 h-9 rounded-full flex items-center justify-center shrink-0 ${iconBg}`}>
                        <Users className="w-4 h-4" />
                      </div>
                      <div className="min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <p className="font-medium text-slate-800 truncate">{s.full_name || s.name}</p>
                          <KindBadge kind={kind} testId={`user-row-${i}-kind`} />
                        </div>
                        <p className="text-xs text-slate-500 truncate">
                          {s.email || (s.age ? `Age: ${s.age}` : 'Protected User')}
                        </p>
                      </div>
                    </div>
                    <Badge className="bg-green-100 text-green-700 shrink-0">
                      {s.status || 'Monitored'}
                    </Badge>
                  </div>
                  );
                })}

                {/* Devices */}
                {drillDown === 'devices' && drillDownData.map((d, i) => (
                  <div key={d.id || i} className="flex items-center justify-between p-3 bg-slate-50 rounded-lg hover:bg-slate-100 transition-colors" data-testid={`device-row-${i}`}>
                    <div className="flex items-center gap-3">
                      <div className={`w-9 h-9 rounded-full flex items-center justify-center ${d.status === 'online' ? 'bg-green-100' : 'bg-slate-200'}`}>
                        <Smartphone className={`w-4 h-4 ${d.status === 'online' ? 'text-green-600' : 'text-slate-500'}`} />
                      </div>
                      <div>
                        <p className="font-medium text-slate-800">{d.device_identifier || 'Device'}</p>
                        <p className="text-xs text-slate-500">{d.senior_name} {d.device_type ? `| ${d.device_type}` : ''}</p>
                      </div>
                    </div>
                    <div className="text-right">
                      <Badge className={d.status === 'online' ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}>
                        {d.status || 'Unknown'}
                      </Badge>
                      {d.last_seen && <p className="text-xs text-slate-400 mt-1">{toIST(d.last_seen)}</p>}
                    </div>
                  </div>
                ))}

                {/* Active / Critical Incidents */}
                {(drillDown === 'active-incidents' || drillDown === 'critical') && drillDownData.map((inc, i) => (
                  <div key={inc.id || i} className={`flex items-center justify-between p-3 rounded-lg transition-colors ${inc.severity === 'critical' ? 'bg-red-50 hover:bg-red-100 border border-red-200' : 'bg-amber-50 hover:bg-amber-100 border border-amber-200'}`} data-testid={`incident-row-${i}`}>
                    <div className="flex items-center gap-3">
                      <AlertTriangle className={`w-5 h-5 ${inc.severity === 'critical' ? 'text-red-500' : 'text-amber-500'}`} />
                      <div>
                        <p className="font-medium text-slate-800">{inc.incident_type || inc.type || 'Incident'}</p>
                        <p className="text-xs text-slate-500">
                          {inc.description?.slice(0, 60) || 'No description'}
                          {inc.created_at && ` | ${toIST(inc.created_at)}`}
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <Badge className={inc.severity === 'critical' ? 'bg-red-200 text-red-800' : 'bg-amber-200 text-amber-800'}>
                        {inc.severity}
                      </Badge>
                      {inc.status === 'open' && (
                        <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => handleAcknowledge(inc.id)} data-testid={`ack-btn-${i}`}>
                          Acknowledge
                        </Button>
                      )}
                    </div>
                  </div>
                ))}

                {/* Online Users */}
                {drillDown === 'online' && drillDownData.map((d, i) => (
                  <div key={d.id || i} className="flex items-center justify-between p-3 bg-green-50 rounded-lg hover:bg-green-100 transition-colors" data-testid={`online-row-${i}`}>
                    <div className="flex items-center gap-3">
                      <div className="w-9 h-9 bg-green-200 rounded-full flex items-center justify-center">
                        <CheckCircle className="w-4 h-4 text-green-600" />
                      </div>
                      <div>
                        <p className="font-medium text-slate-800">{d.senior_name}</p>
                        <p className="text-xs text-slate-500">{d.device_identifier || 'Device'} {d.last_seen && `| Last: ${toIST(d.last_seen)}`}</p>
                      </div>
                    </div>
                    <Badge className="bg-green-100 text-green-700">Active</Badge>
                  </div>
                ))}

                {/* Offline Users */}
                {drillDown === 'offline' && drillDownData.map((d, i) => (
                  <div key={d.id || i} className="flex items-center justify-between p-3 bg-slate-50 rounded-lg hover:bg-slate-100 transition-colors" data-testid={`offline-row-${i}`}>
                    <div className="flex items-center gap-3">
                      <div className="w-9 h-9 bg-slate-200 rounded-full flex items-center justify-center">
                        <XCircle className="w-4 h-4 text-slate-500" />
                      </div>
                      <div>
                        <p className="font-medium text-slate-800">{d.senior_name}</p>
                        <p className="text-xs text-slate-500">{d.device_identifier || 'Device'} {d.last_seen && `| Last: ${toIST(d.last_seen)}`}</p>
                      </div>
                    </div>
                    <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => toast.info('Check-in sent')} data-testid={`checkin-btn-${i}`}>
                      <Send className="w-3 h-3 mr-1" /> Send Check-In
                    </Button>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* SLA Metrics */}
      {sla && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4" data-testid="sla-metrics">
          <Card className="border-l-4 border-l-indigo-500">
            <CardContent className="p-4">
              <div className="flex items-center gap-2 mb-1">
                <Bell className="w-4 h-4 text-indigo-500" />
                <p className="text-xs font-medium text-slate-500 uppercase tracking-wide">Total Incidents</p>
              </div>
              <p className="text-2xl font-bold text-slate-800" data-testid="sla-total">{sla.total_incidents}</p>
            </CardContent>
          </Card>

          <Card className="border-l-4 border-l-teal-500">
            <CardContent className="p-4">
              <div className="flex items-center gap-2 mb-1">
                <CheckCircle className="w-4 h-4 text-teal-500" />
                <p className="text-xs font-medium text-slate-500 uppercase tracking-wide">Acknowledged</p>
              </div>
              <p className="text-2xl font-bold text-slate-800" data-testid="sla-ack">{sla.acknowledged_count}</p>
            </CardContent>
          </Card>

          <Card className="border-l-4 border-l-amber-500">
            <CardContent className="p-4">
              <div className="flex items-center gap-2 mb-1">
                <Clock className="w-4 h-4 text-amber-500" />
                <p className="text-xs font-medium text-slate-500 uppercase tracking-wide">Avg Time to Ack</p>
              </div>
              <p className="text-2xl font-bold text-slate-800" data-testid="sla-avg-ack">{formatSeconds(sla.avg_time_to_ack_seconds)}</p>
            </CardContent>
          </Card>

          <Card className="border-l-4 border-l-emerald-500">
            <CardContent className="p-4">
              <div className="flex items-center gap-2 mb-1">
                <Timer className="w-4 h-4 text-emerald-500" />
                <p className="text-xs font-medium text-slate-500 uppercase tracking-wide">Avg Time to Resolve</p>
              </div>
              <p className="text-2xl font-bold text-slate-800" data-testid="sla-avg-resolve">{formatSeconds(sla.avg_time_to_resolve_seconds)}</p>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Status Summary */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Activity className="w-5 h-5 text-teal-500" />
              System Status
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              <div className="flex items-center justify-between p-3 bg-slate-50 rounded-lg">
                <span className="text-slate-600">Monitoring Service</span>
                <Badge className="bg-green-100 text-green-700">Active</Badge>
              </div>
              <div className="flex items-center justify-between p-3 bg-slate-50 rounded-lg">
                <span className="text-slate-600">Incident Detection</span>
                <Badge className="bg-green-100 text-green-700">Active</Badge>
              </div>
              <div className="flex items-center justify-between p-3 bg-slate-50 rounded-lg">
                <span className="text-slate-600">Device Sync</span>
                <Badge className="bg-green-100 text-green-700">Active</Badge>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Bell className="w-5 h-5 text-amber-500" />
              Quick Actions
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              <Button 
                className="w-full justify-start bg-teal-600 hover:bg-teal-700"
                onClick={() => window.location.href = '/family/incidents'}
              >
                <Bell className="w-4 h-4 mr-2" />
                View All Incidents
              </Button>
              <Button 
                variant="outline" 
                className="w-full justify-start"
                onClick={() => window.location.href = '/family/seniors'}
              >
                <Users className="w-4 h-4 mr-2" />
                Manage Users
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
};

const IncidentsPage = () => {
  const { user } = useAuth();
  const [incidents, setIncidents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [events, setEvents] = useState([]);
  const [eventsLoading, setEventsLoading] = useState(false);
  const [notifJobs, setNotifJobs] = useState([]);

  const fetchIncidents = async () => {
    try {
      const data = await incidentsApi.getIncidents(user.id);
      setIncidents(data);
    } catch (error) {
      toast.error('Failed to load incidents');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (user?.id) {
      fetchIncidents();
    }
  }, [user]);

  const fetchEvents = async (incidentId) => {
    if (selectedId === incidentId) {
      setSelectedId(null);
      setEvents([]);
      setNotifJobs([]);
      return;
    }
    setSelectedId(incidentId);
    setEventsLoading(true);
    try {
      const [eventsRes, jobsRes] = await Promise.all([
        api.get(`/incidents/${incidentId}/events`),
        api.get(`/incidents/${incidentId}/notification-jobs`),
      ]);
      setEvents([...eventsRes.data].sort((a, b) => new Date(a.created_at) - new Date(b.created_at)));
      setNotifJobs(jobsRes.data);
    } catch {
      toast.error('Failed to load timeline');
    } finally {
      setEventsLoading(false);
    }
  };

  const getEventIcon = (type) => {
    switch (type) {
      case 'incident_created': return <AlertTriangle className="w-4 h-4 text-red-500" />;
      case 'escalation_l1': return <Bell className="w-4 h-4 text-orange-500" />;
      case 'escalation_l2': return <Bell className="w-4 h-4 text-red-600" />;
      case 'acknowledged': return <CheckCircle className="w-4 h-4 text-blue-500" />;
      case 'resolve': return <CheckCircle className="w-4 h-4 text-green-500" />;
      case 'false_alarm': return <XCircle className="w-4 h-4 text-slate-500" />;
      default: return <Activity className="w-4 h-4 text-slate-400" />;
    }
  };

  const getEventColor = (type) => {
    switch (type) {
      case 'incident_created': return 'border-red-400';
      case 'escalation_l1': return 'border-orange-400';
      case 'escalation_l2': return 'border-red-500';
      case 'acknowledged': return 'border-blue-400';
      case 'resolve': return 'border-green-400';
      case 'false_alarm': return 'border-slate-400';
      default: return 'border-slate-300';
    }
  };

  const handleAcknowledge = async (incidentId) => {
    setActionLoading(incidentId);
    try {
      await incidentsApi.acknowledge(incidentId);
      toast.success('Incident acknowledged');
      fetchIncidents();
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Failed to acknowledge');
    } finally {
      setActionLoading(null);
    }
  };

  const handleResolve = async (incidentId) => {
    setActionLoading(incidentId);
    try {
      await incidentsApi.resolve(incidentId);
      toast.success('Incident resolved');
      fetchIncidents();
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Failed to resolve');
    } finally {
      setActionLoading(null);
    }
  };

  const handleFalseAlarm = async (incidentId) => {
    setActionLoading(incidentId);
    try {
      await incidentsApi.markFalseAlarm(incidentId);
      toast.success('Marked as false alarm');
      fetchIncidents();
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Failed to mark false alarm');
    } finally {
      setActionLoading(null);
    }
  };

  const getSeverityColor = (severity) => {
    switch (severity) {
      case 'critical': return 'bg-red-100 text-red-700';
      case 'high': return 'bg-orange-100 text-orange-700';
      case 'medium': return 'bg-yellow-100 text-yellow-700';
      default: return 'bg-slate-100 text-slate-700';
    }
  };

  const getStatusColor = (status) => {
    switch (status) {
      case 'open': return 'bg-red-100 text-red-700';
      case 'acknowledged': return 'bg-amber-100 text-amber-700';
      case 'resolved': return 'bg-green-100 text-green-700';
      case 'false_alarm': return 'bg-slate-100 text-slate-700';
      default: return 'bg-slate-100 text-slate-700';
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-8 h-8 animate-spin text-teal-600" />
      </div>
    );
  }

  return (
    <div className="space-y-6" data-testid="incidents-page">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold text-slate-800">Incidents</h2>
        <Button variant="outline" size="sm" onClick={fetchIncidents}>
          <RefreshCw className="w-4 h-4 mr-2" />
          Refresh
        </Button>
      </div>

      {incidents.length === 0 ? (
        <Card>
          <CardContent className="p-12 text-center">
            <CheckCircle className="w-12 h-12 mx-auto text-green-500 mb-4" />
            <h3 className="text-lg font-medium text-slate-700">No incidents — all clear</h3>
            <p className="text-slate-500 mt-1">None of your loved ones has triggered an emergency.</p>
            <div className="mt-5 text-left max-w-md mx-auto bg-slate-50 rounded-lg p-4">
              <p className="text-xs font-semibold text-slate-600 uppercase tracking-wide mb-2">Incidents appear here when:</p>
              <ul className="text-xs text-slate-500 space-y-1.5 list-disc list-inside">
                <li>A child/senior taps the SOS button in the mobile app</li>
                <li>The AI Brain detects a sustained high-risk pattern</li>
                <li>A route deviation escalates to Level 2 or higher</li>
                <li>A device reports a fall or voice distress signal</li>
              </ul>
            </div>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          {incidents.map((incident) => (
            <Card key={incident.id} className="overflow-hidden" data-testid={`incident-${incident.id}`}>
              <CardContent className="p-0">
                <div className="flex items-stretch">
                  <div className={`w-2 ${incident.severity === 'critical' ? 'bg-red-500' : incident.severity === 'high' ? 'bg-orange-500' : 'bg-yellow-500'}`} />
                  <div className="flex-1 p-4">
                    <div className="flex items-start justify-between">
                      <div>
                        <div className="flex items-center gap-2 mb-1">
                          <h3 className="font-semibold text-slate-800">{incident.incident_type}</h3>
                          <Badge className={getSeverityColor(incident.severity)}>
                            {incident.severity}
                          </Badge>
                          <Badge className={getStatusColor(incident.status)}>
                            {incident.status}
                          </Badge>
                        </div>
                        <p className="text-sm text-slate-500">
                          Created: {new Date(incident.created_at).toLocaleString()}
                        </p>
                        {incident.resolved_at && (
                          <p className="text-sm text-slate-500">
                            Resolved: {new Date(incident.resolved_at).toLocaleString()}
                          </p>
                        )}
                        {incident.escalation_level > 1 && (
                          <span className="inline-flex items-center text-xs font-medium text-red-600 mt-1">
                            Escalation Level {incident.escalation_level}
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-2">
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => fetchEvents(incident.id)}
                          data-testid={`timeline-btn-${incident.id}`}
                        >
                          <Clock className="w-4 h-4 mr-1" />
                          {selectedId === incident.id ? 'Hide' : 'Timeline'}
                        </Button>
                      {(incident.status === 'open' || incident.status === 'acknowledged') && (
                        <div className="flex gap-2">
                          {incident.status === 'open' && (
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => handleAcknowledge(incident.id)}
                              disabled={actionLoading === incident.id}
                              data-testid={`ack-btn-${incident.id}`}
                            >
                              {actionLoading === incident.id ? (
                                <Loader2 className="w-4 h-4 animate-spin" />
                              ) : (
                                'Acknowledge'
                              )}
                            </Button>
                          )}
                          <Button
                            size="sm"
                            className="bg-green-600 hover:bg-green-700"
                            onClick={() => handleResolve(incident.id)}
                            disabled={actionLoading === incident.id}
                            data-testid={`resolve-btn-${incident.id}`}
                          >
                            {actionLoading === incident.id ? (
                              <Loader2 className="w-4 h-4 animate-spin" />
                            ) : (
                              'Resolve'
                            )}
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => handleFalseAlarm(incident.id)}
                            disabled={actionLoading === incident.id}
                            data-testid={`false-alarm-btn-${incident.id}`}
                          >
                            False Alarm
                          </Button>
                        </div>
                      )}
                      </div>
                    </div>
                    {/* Timeline Panel */}
                    {selectedId === incident.id && (
                      <div className="mt-4 pt-4 border-t border-slate-100" data-testid={`timeline-${incident.id}`}>
                        <h4 className="text-sm font-semibold text-slate-700 mb-3">Incident Timeline</h4>
                        {eventsLoading ? (
                          <div className="flex items-center gap-2 text-sm text-slate-400">
                            <Loader2 className="w-4 h-4 animate-spin" /> Loading...
                          </div>
                        ) : events.length === 0 ? (
                          <p className="text-sm text-slate-400">No events recorded</p>
                        ) : (
                          <div className="space-y-3">
                            {events.map((event) => (
                              <div key={event.id} className={`border-l-2 ${getEventColor(event.event_type)} pl-3 py-1`}>
                                <div className="flex items-center gap-2">
                                  {getEventIcon(event.event_type)}
                                  <span className="text-sm font-medium text-slate-700 capitalize">
                                    {event.event_type.replace(/_/g, ' ')}
                                  </span>
                                  {event.event_channel && (
                                    <span className="text-xs px-1.5 py-0.5 rounded bg-slate-100 text-slate-500">
                                      {event.event_channel}
                                    </span>
                                  )}
                                </div>
                                <p className="text-xs text-slate-400 mt-0.5">
                                  {new Date(event.created_at).toLocaleString()}
                                </p>
                              </div>
                            ))}
                          </div>
                        )}
                        {/* Notification Delivery Status */}
                        {!eventsLoading && notifJobs.length > 0 && (
                          <div className="mt-4 pt-3 border-t border-slate-100" data-testid={`notif-jobs-${incident.id}`}>
                            <h4 className="text-sm font-semibold text-slate-700 mb-2 flex items-center gap-1.5">
                              <Send className="w-3.5 h-3.5 text-slate-500" />
                              Notification Delivery ({notifJobs.length})
                            </h4>
                            <div className="space-y-1.5">
                              {notifJobs.map((job) => {
                                const chIcon = job.channel === 'email' ? <Mail className="w-3.5 h-3.5" /> 
                                  : job.channel === 'sms' ? <MessageSquare className="w-3.5 h-3.5" /> 
                                  : <Zap className="w-3.5 h-3.5" />;
                                const stColor = job.status === 'sent' ? 'text-emerald-600 bg-emerald-50'
                                  : job.status === 'dead_letter' ? 'text-red-600 bg-red-50'
                                  : job.status === 'retrying' ? 'text-orange-600 bg-orange-50'
                                  : job.status === 'cancelled' ? 'text-slate-500 bg-slate-50'
                                  : 'text-yellow-600 bg-yellow-50';
                                return (
                                  <div key={job.id} className="flex items-center gap-2 text-xs py-1 px-2 rounded bg-slate-50" data-testid={`notif-job-${job.id}`}>
                                    <span className="text-slate-400">{chIcon}</span>
                                    <span className="text-slate-600 font-mono truncate max-w-[140px]">{job.recipient}</span>
                                    <span className={`px-1.5 py-0.5 rounded font-medium ${stColor}`}>{job.status}</span>
                                    {job.escalation_level && (
                                      <span className="text-slate-400">L{job.escalation_level}</span>
                                    )}
                                    {job.attempts > 0 && (
                                      <span className="text-slate-400">x{job.attempts}</span>
                                    )}
                                    {job.status === 'dead_letter' && (
                                      <SkullIcon className="w-3 h-3 text-red-500" />
                                    )}
                                  </div>
                                );
                              })}
                            </div>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
};

const SeniorsPage = () => {
  const { user } = useAuth();
  const [seniors, setSeniors] = useState([]);
  const [lovedOnes, setLovedOnes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedSenior, setSelectedSenior] = useState(null);
  const [devices, setDevices] = useState([]);
  const [telemetry, setTelemetry] = useState([]);

  // Add Senior form
  const [showAddSenior, setShowAddSenior] = useState(false);
  const [newSenior, setNewSenior] = useState({ full_name: '', age: '', medical_notes: '' });
  const [addingSenior, setAddingSenior] = useState(false);

  // Link Device form
  const [showLinkDevice, setShowLinkDevice] = useState(false);
  const [newDevice, setNewDevice] = useState({ device_identifier: '', device_type: '' });
  const [linkingDevice, setLinkingDevice] = useState(false);

  // Test Alert
  const [testAlertStatus, setTestAlertStatus] = useState(null); // null | 'sending' | 'sent' | 'error'
  const [testAlertResult, setTestAlertResult] = useState(null);

  // Live per-child risk (SSE-driven via `risk_update` from the backend
  // `risk_emitter`). Keyed by `child_id`. Hydrated by a 60s safety-net
  // poll of /api/guardian/live/risk and kept fresh by SSE pushes.
  const [liveRisk, setLiveRisk] = useState({});

  // Hydrate liveRisk on mount + every 60s (safety net for missed SSE).
  useEffect(() => {
    let cancelled = false;
    const hydrate = async () => {
      try {
        const res = await api.get('/guardian/live/risk');
        if (cancelled) return;
        const rows = Array.isArray(res.data) ? res.data : [];
        if (rows.length === 0) return;
        setLiveRisk((prev) => {
          const next = { ...(prev || {}) };
          for (const row of rows) {
            const id = String(row.child_id || '');
            if (!id) continue;
            // Only overwrite if we have nothing or no version yet — SSE
            // updates carry a monotonic `version`; the poll fallback
            // doesn't, so we never use it to displace SSE state.
            if (!next[id] || !next[id].version) {
              next[id] = { ...row };
            }
          }
          return next;
        });
      } catch (e) {
        // non-fatal — endpoint has its own fallback dict already.
      }
    };
    hydrate();
    const iv = setInterval(hydrate, 60_000);
    return () => { cancelled = true; clearInterval(iv); };
  }, []);

  const fetchSeniors = async () => {
    try {
      const data = await seniorsApi.getMySeniors();
      setSeniors(data);
    } catch {
      toast.error('Failed to load seniors');
    } finally {
      setLoading(false);
    }
  };

  const fetchLovedOnes = async () => {
    try {
      const res = await api.get('/guardian/dashboard/loved-ones');
      setLovedOnes(res.data?.monitored_users || []);
    } catch {
      // non-fatal: this endpoint may be empty for non-guardian roles
    }
  };

  useEffect(() => { fetchSeniors(); fetchLovedOnes(); }, []);

  const handleAddSenior = async (e) => {
    e.preventDefault();
    if (!newSenior.full_name.trim()) { toast.error('Name is required'); return; }
    setAddingSenior(true);
    try {
      const created = await seniorsApi.createMySenior({
        full_name: newSenior.full_name.trim(),
        age: newSenior.age ? parseInt(newSenior.age) : null,
        medical_notes: newSenior.medical_notes || null,
      });
      setSeniors(prev => [...prev, created]);
      setNewSenior({ full_name: '', age: '', medical_notes: '' });
      setShowAddSenior(false);
      toast.success(`${created.full_name} added`);
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Failed to add senior');
    } finally { setAddingSenior(false); }
  };

  const handleSelectSenior = async (senior) => {
    setSelectedSenior(senior);
    setDevices([]);
    setTelemetry([]);
    try {
      const devicesData = await devicesApi.getMyDevices(senior.id);
      setDevices(devicesData);
      if (devicesData.length > 0) {
        const telemetryData = await devicesApi.getTelemetry(devicesData[0].id, 20);
        setTelemetry(telemetryData);
      }
    } catch {
      toast.error('Failed to load devices');
    }
  };

  const handleLinkDevice = async (e) => {
    e.preventDefault();
    if (!newDevice.device_identifier.trim()) { toast.error('Device ID is required'); return; }
    setLinkingDevice(true);
    try {
      const created = await devicesApi.linkDevice(selectedSenior.id, {
        device_identifier: newDevice.device_identifier.trim(),
        device_type: newDevice.device_type || null,
      });
      setDevices(prev => [...prev, created]);
      setNewDevice({ device_identifier: '', device_type: '' });
      setShowLinkDevice(false);
      toast.success(`Device ${created.device_identifier} linked`);
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Failed to link device');
    } finally { setLinkingDevice(false); }
  };

  const handleDeviceSelect = async (deviceId) => {
    try {
      const telemetryData = await devicesApi.getTelemetry(deviceId, 20);
      setTelemetry(telemetryData);
    } catch {
      toast.error('Failed to load telemetry');
    }
  };

  const sendTestAlert = async (alertType = 'sos') => {
    if (!selectedSenior || devices.length === 0) return;
    setTestAlertStatus('sending');
    setTestAlertResult(null);
    try {
      const { data } = await api.post(`/my/seniors/${selectedSenior.id}/test-alert`, {
        device_identifier: devices[0].device_identifier,
        type: alertType,
      });
      setTestAlertStatus('sent');
      setTestAlertResult(data);
      toast.success(`Test ${alertType} alert sent for ${selectedSenior.full_name}`);
    } catch (error) {
      setTestAlertStatus('error');
      toast.error(error.response?.data?.detail || 'Failed to send test alert');
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-8 h-8 animate-spin text-teal-600" />
      </div>
    );
  }

  return (
    <div className="space-y-6" data-testid="seniors-page">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold text-slate-800">Protected Users</h2>
        <Button
          onClick={() => setShowAddSenior(true)}
          className="bg-teal-600 hover:bg-teal-700"
          data-testid="add-senior-btn"
        >
          <UserPlus className="w-4 h-4 mr-2" />
          Add Senior
        </Button>
      </div>

      {/* Loved Ones (children + women linked via guardian relationships) */}
      {lovedOnes.length > 0 && (
        <Card data-testid="loved-ones-section">
          <CardHeader className="pb-3">
            <CardTitle className="text-lg flex items-center gap-2 text-slate-800">
              <Heart className="w-5 h-5 text-rose-500" />
              Loved Ones
              <Badge variant="outline" className="ml-2 text-xs">{lovedOnes.length}</Badge>
            </CardTitle>
            <CardDescription>Children and family members linked to you via the mobile app</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {lovedOnes.map((lo) => {
                const statusColor = lo.status === 'SAFE' ? 'bg-emerald-100 text-emerald-700'
                  : lo.status === 'HIGH' ? 'bg-red-100 text-red-700'
                  : lo.status === 'CRITICAL' ? 'bg-red-200 text-red-800'
                  : 'bg-slate-100 text-slate-600';
                return (
                  <div key={lo.user_id} className="p-3 rounded-lg border border-slate-200 bg-slate-50 hover:bg-white transition"
                    data-testid={`loved-one-${lo.user_id}`}>
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-2">
                        <div className="w-9 h-9 rounded-full bg-teal-500 text-white font-bold flex items-center justify-center text-sm">
                          {(lo.name || 'U')[0]}
                        </div>
                        <div>
                          <div className="flex items-center gap-1.5 flex-wrap">
                            <p className="font-semibold text-slate-800 text-sm">{lo.name}</p>
                            <KindBadge kind={lo.role} size="xs" testId={`loved-one-${lo.user_id}-kind`} />
                          </div>
                          <p className="text-xs text-slate-500 capitalize">{lo.role} · {lo.relationship}</p>
                        </div>
                      </div>
                      <Badge className={statusColor}>{lo.status || '--'}</Badge>
                    </div>
                    <div className="text-xs text-slate-500 space-y-0.5">
                      {lo.email && <p className="truncate"><span className="text-slate-400">Email:</span> {lo.email}</p>}
                      {lo.phone && <p><span className="text-slate-400">Phone:</span> {lo.phone}</p>}
                      {lo.location && (
                        <p>
                          <span className="text-slate-400">Last location:</span>{' '}
                          {lo.location.lat.toFixed(4)}, {lo.location.lng.toFixed(4)}
                          {lo.last_updated && (
                            <span className="text-slate-400"> · {formatRelativeTime(lo.last_updated)}</span>
                          )}
                        </p>
                      )}
                      {lo.has_active_session ? (
                        <p className="text-teal-600 font-medium mt-1">● Journey active</p>
                      ) : (
                        <p className="text-slate-400 mt-1">○ No active journey</p>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Add Senior Form */}
      {showAddSenior && (
        <Card className="border-teal-200 bg-teal-50/50" data-testid="add-senior-form">
          <CardHeader className="pb-2">
            <CardTitle className="text-lg flex items-center gap-2">
              <UserPlus className="w-5 h-5 text-teal-600" />
              Add a Senior
            </CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleAddSenior} className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="space-y-1">
                <label className="text-sm font-medium text-slate-700">Full Name *</label>
                <input
                  type="text" className="w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-teal-300 focus:border-teal-400 outline-none"
                  placeholder="e.g. Grandma Kamala"
                  value={newSenior.full_name} onChange={(e) => setNewSenior(p => ({ ...p, full_name: e.target.value }))}
                  data-testid="senior-name-input" disabled={addingSenior}
                />
              </div>
              <div className="space-y-1">
                <label className="text-sm font-medium text-slate-700">Age</label>
                <input
                  type="number" className="w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-teal-300 focus:border-teal-400 outline-none"
                  placeholder="e.g. 78" min="0" max="150"
                  value={newSenior.age} onChange={(e) => setNewSenior(p => ({ ...p, age: e.target.value }))}
                  data-testid="senior-age-input" disabled={addingSenior}
                />
              </div>
              <div className="space-y-1">
                <label className="text-sm font-medium text-slate-700">Medical Notes</label>
                <input
                  type="text" className="w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-teal-300 focus:border-teal-400 outline-none"
                  placeholder="e.g. Diabetes, mild dementia"
                  value={newSenior.medical_notes} onChange={(e) => setNewSenior(p => ({ ...p, medical_notes: e.target.value }))}
                  data-testid="senior-notes-input" disabled={addingSenior}
                />
              </div>
              <div className="md:col-span-3 flex gap-2 justify-end">
                <Button type="button" variant="outline" onClick={() => setShowAddSenior(false)} disabled={addingSenior}>Cancel</Button>
                <Button type="submit" className="bg-teal-600 hover:bg-teal-700" disabled={addingSenior} data-testid="senior-submit-btn">
                  {addingSenior ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : null}
                  Add Senior
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Seniors List */}
        <Card>
          <CardHeader>
            <CardTitle>Seniors & Devices</CardTitle>
            <CardDescription>Elderly care — select a senior to view their devices & telemetry</CardDescription>
          </CardHeader>
          <CardContent>
            {seniors.length === 0 ? (
              <div className="text-center py-6">
                <Users className="w-10 h-10 text-slate-300 mx-auto mb-2" />
                <p className="text-slate-500 text-sm">No seniors registered yet</p>
                <Button variant="outline" size="sm" className="mt-3" onClick={() => setShowAddSenior(true)} data-testid="empty-add-senior-btn">
                  <UserPlus className="w-3.5 h-3.5 mr-1" /> Add your first senior
                </Button>
              </div>
            ) : (
              <div className="space-y-2">
                {seniors.map((senior) => (
                  <Button
                    key={senior.id}
                    variant={selectedSenior?.id === senior.id ? 'default' : 'outline'}
                    className="w-full justify-start gap-2"
                    onClick={() => handleSelectSenior(senior)}
                    data-testid={`senior-btn-${senior.id}`}
                  >
                    <Users className="w-4 h-4" />
                    <span className="truncate">{senior.full_name}</span>
                    <KindBadge kind="senior" size="xs" />
                    {senior.age && <span className="ml-auto text-sm opacity-70">{senior.age} yrs</span>}
                  </Button>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Devices */}
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <div>
                <CardTitle>Devices</CardTitle>
                <CardDescription>
                  {selectedSenior ? `Devices for ${selectedSenior.full_name}` : 'Select a senior'}
                </CardDescription>
              </div>
              {selectedSenior && (
                <Button variant="outline" size="sm" onClick={() => setShowLinkDevice(true)} data-testid="link-device-btn">
                  <LinkIcon className="w-3.5 h-3.5 mr-1" /> Link Device
                </Button>
              )}
            </div>
          </CardHeader>
          <CardContent>
            {/* Link Device Form */}
            {showLinkDevice && selectedSenior && (
              <form onSubmit={handleLinkDevice} className="mb-4 p-3 bg-teal-50 rounded-lg space-y-3" data-testid="link-device-form">
                <div className="space-y-1">
                  <label className="text-xs font-medium text-slate-600">Device ID *</label>
                  <input
                    type="text" className="w-full px-2 py-1.5 border rounded text-sm focus:ring-2 focus:ring-teal-300 outline-none"
                    placeholder="e.g. WBAND-001"
                    value={newDevice.device_identifier} onChange={(e) => setNewDevice(p => ({ ...p, device_identifier: e.target.value }))}
                    data-testid="device-id-input" disabled={linkingDevice}
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-xs font-medium text-slate-600">Type</label>
                  <input
                    type="text" className="w-full px-2 py-1.5 border rounded text-sm focus:ring-2 focus:ring-teal-300 outline-none"
                    placeholder="e.g. wristband, pendant"
                    value={newDevice.device_type} onChange={(e) => setNewDevice(p => ({ ...p, device_type: e.target.value }))}
                    data-testid="device-type-input" disabled={linkingDevice}
                  />
                </div>
                <div className="flex gap-2 justify-end">
                  <Button type="button" variant="outline" size="sm" onClick={() => setShowLinkDevice(false)}>Cancel</Button>
                  <Button type="submit" size="sm" className="bg-teal-600 hover:bg-teal-700" disabled={linkingDevice} data-testid="device-submit-btn">
                    {linkingDevice ? <Loader2 className="w-3.5 h-3.5 mr-1 animate-spin" /> : null}
                    Link
                  </Button>
                </div>
              </form>
            )}

            {!selectedSenior ? (
              <p className="text-slate-500 text-center py-4">Select a senior first</p>
            ) : devices.length === 0 && !showLinkDevice ? (
              <div className="text-center py-4">
                <Smartphone className="w-8 h-8 text-slate-300 mx-auto mb-2" />
                <p className="text-slate-500 text-sm">No devices linked</p>
                <Button variant="outline" size="sm" className="mt-2" onClick={() => setShowLinkDevice(true)} data-testid="empty-link-device-btn">
                  <LinkIcon className="w-3.5 h-3.5 mr-1" /> Link first device
                </Button>
              </div>
            ) : (
              <div className="space-y-2">
                {devices.map((device) => (
                  <div
                    key={device.id}
                    className="p-3 bg-slate-50 rounded-lg cursor-pointer hover:bg-slate-100"
                    onClick={() => handleDeviceSelect(device.id)}
                    data-testid={`device-${device.id}`}
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <Smartphone className="w-4 h-4 text-slate-500" />
                        <span className="font-medium">{device.device_identifier}</span>
                      </div>
                      <DeviceStatusBadge status={device.last_seen ? device.status : null} />
                    </div>
                    <div className="flex items-center justify-between mt-1">
                      {device.device_type && (
                        <p className="text-sm text-slate-500">{device.device_type}</p>
                      )}
                      <p className="text-xs text-muted-foreground ml-auto" data-testid={`device-last-seen-${device.id}`}>
                        Last seen: {formatRelativeTime(device.last_seen)}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Telemetry */}
        <Card>
          <CardHeader>
            <CardTitle>Telemetry History</CardTitle>
            <CardDescription>Recent device data</CardDescription>
          </CardHeader>
          <CardContent>
            {telemetry.length === 0 ? (
              <p className="text-slate-500 text-center py-4">No telemetry data</p>
            ) : (
              <div className="space-y-2 max-h-80 overflow-y-auto">
                {telemetry.map((t) => (
                  <div key={t.id} className="p-2 bg-slate-50 rounded text-sm">
                    <div className="flex items-center justify-between">
                      <Badge variant="outline">{t.metric_type}</Badge>
                      <span className="text-xs text-slate-400">
                        {new Date(t.created_at).toLocaleTimeString()}
                      </span>
                    </div>
                    <pre className="text-xs text-slate-600 mt-1 overflow-x-auto">
                      {JSON.stringify(t.metric_value, null, 2)}
                    </pre>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Device Health */}
      {selectedSenior && devices.length > 0 && (
        <DeviceHealthCard seniorId={selectedSenior.id} />
      )}

      {/* Test Alert Card */}
      {selectedSenior && devices.length > 0 && (
        <Card className={`border-2 ${testAlertStatus === 'sent' ? 'border-emerald-300 bg-emerald-50/50' : testAlertStatus === 'error' ? 'border-red-300 bg-red-50/50' : 'border-amber-200 bg-gradient-to-r from-amber-50 to-orange-50'}`} data-testid="test-alert-card">
          <CardContent className="p-6">
            {testAlertStatus === 'sent' && testAlertResult ? (
              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <CheckCircle className="w-6 h-6 text-emerald-600" />
                  <h3 className="text-lg font-semibold text-emerald-800">Test Alert Sent!</h3>
                </div>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
                  <div className="bg-white rounded-lg p-3 border border-emerald-100">
                    <p className="text-xs text-slate-500 mb-1">Incident</p>
                    <p className="font-mono text-xs text-slate-700 truncate" data-testid="test-alert-incident-id">{testAlertResult.incident_id}</p>
                  </div>
                  <div className="bg-white rounded-lg p-3 border border-emerald-100">
                    <p className="text-xs text-slate-500 mb-1">Type</p>
                    <p className="font-medium text-slate-700">{testAlertResult.incident_type}</p>
                  </div>
                  <div className="bg-white rounded-lg p-3 border border-emerald-100">
                    <p className="text-xs text-slate-500 mb-1">Severity</p>
                    <Badge className="bg-red-100 text-red-700">{testAlertResult.severity}</Badge>
                  </div>
                  <div className="bg-white rounded-lg p-3 border border-emerald-100">
                    <p className="text-xs text-slate-500 mb-1">Pipeline</p>
                    <p className="text-xs text-emerald-600 font-medium">Full escalation active</p>
                  </div>
                </div>
                <p className="text-xs text-slate-500">
                  Escalation will trigger at 30s (L1), 60s (L2), 90s (L3). Auto-resolves after 2 minutes.
                  Check your Incidents tab to see the live timeline.
                </p>
                <Button variant="outline" size="sm" onClick={() => { setTestAlertStatus(null); setTestAlertResult(null); }}>
                  Dismiss
                </Button>
              </div>
            ) : (
              <div className="flex items-center justify-between gap-4">
                <div className="flex items-center gap-3">
                  <div className="w-12 h-12 rounded-xl bg-amber-100 flex items-center justify-center">
                    <AlertTriangle className="w-6 h-6 text-amber-600" />
                  </div>
                  <div>
                    <h3 className="font-semibold text-slate-800">Test Your Alert System</h3>
                    <p className="text-sm text-slate-500">
                      Send a test SOS alert for {selectedSenior.full_name} through the full pipeline.
                    </p>
                  </div>
                </div>
                <Button
                  onClick={() => sendTestAlert('sos')}
                  className="bg-amber-500 hover:bg-amber-600 text-white shrink-0"
                  disabled={testAlertStatus === 'sending'}
                  data-testid="send-test-alert-btn"
                >
                  {testAlertStatus === 'sending' ? (
                    <><Loader2 className="w-4 h-4 mr-2 animate-spin" />Sending...</>
                  ) : (
                    <><Bell className="w-4 h-4 mr-2" />Send Test Alert</>
                  )}
                </Button>
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
};

const SettingsPage = () => {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  // Notification preferences: persist in localStorage + backend (best-effort)
  const [prefs, setPrefs] = useState(() => {
    try {
      const saved = JSON.parse(localStorage.getItem('nischint_notif_prefs') || '{}');
      return {
        push: saved.push !== false,     // default ON
        email: saved.email !== false,   // default ON
        sms: saved.sms === true,        // default OFF (costs money)
        sos_critical: saved.sos_critical !== false,  // default ON (can't turn off)
        daily_digest: saved.daily_digest === true,
        weekly_report: saved.weekly_report === true,
      };
    } catch { return { push: true, email: true, sms: false, sos_critical: true, daily_digest: false, weekly_report: false }; }
  });
  const [saving, setSaving] = useState(false);
  const [enablingPush, setEnablingPush] = useState(false);

  const updatePref = (key, value) => {
    const next = { ...prefs, [key]: value };
    setPrefs(next);
    try { localStorage.setItem('nischint_notif_prefs', JSON.stringify(next)); } catch {}
    // Best-effort sync to backend
    (async () => {
      setSaving(true);
      try { await api.patch('/my/notification-preferences', next); } catch {}
      setSaving(false);
    })();
  };

  const enableBrowserPush = async () => {
    setEnablingPush(true);
    try {
      const token = await requestPushToken();
      if (token) {
        toast.success('Browser push enabled — you will now receive live alerts');
        updatePref('push', true);
      } else {
        toast.error('Could not enable push. Please allow notifications in your browser settings.');
      }
    } catch (e) {
      toast.error('Push not supported in this browser');
    }
    setEnablingPush(false);
  };

  const handleLogout = async () => {
    await logout();
    navigate('/login');
  };

  const Toggle = ({ enabled, onChange, disabled }) => (
    <button
      onClick={() => !disabled && onChange(!enabled)}
      disabled={disabled}
      className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
        enabled ? 'bg-teal-600' : 'bg-slate-300'
      } ${disabled ? 'opacity-40 cursor-not-allowed' : 'cursor-pointer'}`}
    >
      <span className={`inline-block h-5 w-5 transform rounded-full bg-white shadow transition-transform ${
        enabled ? 'translate-x-5' : 'translate-x-0.5'
      }`} />
    </button>
  );

  return (
    <div className="space-y-6" data-testid="settings-page">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-slate-800">Settings</h2>
          <p className="text-sm text-slate-500">Manage your account and how you receive alerts</p>
        </div>
        {saving && <span className="text-xs text-slate-400 flex items-center gap-1"><Loader2 className="w-3 h-3 animate-spin" /> Saving…</span>}
      </div>

      {/* Account Info */}
      <Card data-testid="settings-account">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-lg">
            <Users className="w-5 h-5 text-teal-600" />
            Account
          </CardTitle>
          <CardDescription>Your profile information (read-only)</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex items-center gap-4">
            <div className="w-14 h-14 rounded-full bg-teal-600 text-white flex items-center justify-center text-xl font-bold">
              {(user?.full_name || user?.email || 'U')[0].toUpperCase()}
            </div>
            <div className="flex-1">
              <p className="font-semibold text-slate-800">{user?.full_name || '—'}</p>
              <p className="text-sm text-slate-500">{user?.email}</p>
              <div className="flex gap-1 mt-1">
                <Badge variant="outline" className="text-xs capitalize">{user?.role}</Badge>
                {user?.roles?.includes('admin') && <Badge className="text-xs bg-red-500/20 text-red-700 border-red-500/30">Admin</Badge>}
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Notification Preferences */}
      <Card data-testid="settings-notifications">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-lg">
            <Bell className="w-5 h-5 text-amber-500" />
            Notification Preferences
          </CardTitle>
          <CardDescription>Choose how you want to receive alerts and reports</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Push */}
          <div className="flex items-start justify-between gap-4 pb-3 border-b">
            <div className="flex-1">
              <div className="flex items-center gap-2">
                <p className="font-medium text-slate-800">Browser push notifications</p>
                <Badge variant="outline" className="text-[10px]">Real-time</Badge>
              </div>
              <p className="text-xs text-slate-500 mt-0.5">Instant SOS, risk, and check-in alerts in your browser</p>
              {!prefs.push && (
                <Button size="sm" variant="outline" onClick={enableBrowserPush} disabled={enablingPush} className="mt-2 text-xs">
                  {enablingPush ? <Loader2 className="w-3 h-3 mr-1 animate-spin" /> : <Zap className="w-3 h-3 mr-1" />}
                  Enable browser push
                </Button>
              )}
            </div>
            <Toggle enabled={prefs.push} onChange={(v) => updatePref('push', v)} />
          </div>

          {/* Email */}
          <div className="flex items-center justify-between gap-4 pb-3 border-b">
            <div className="flex-1">
              <p className="font-medium text-slate-800">Email alerts</p>
              <p className="text-xs text-slate-500 mt-0.5">Delivered to {user?.email}</p>
            </div>
            <Toggle enabled={prefs.email} onChange={(v) => updatePref('email', v)} />
          </div>

          {/* SMS */}
          <div className="flex items-center justify-between gap-4 pb-3 border-b">
            <div className="flex-1">
              <div className="flex items-center gap-2">
                <p className="font-medium text-slate-800">SMS alerts</p>
                <Badge variant="outline" className="text-[10px] bg-amber-50 border-amber-200 text-amber-700">Charges apply</Badge>
              </div>
              <p className="text-xs text-slate-500 mt-0.5">Critical SOS only, via Twilio</p>
            </div>
            <Toggle enabled={prefs.sms} onChange={(v) => updatePref('sms', v)} />
          </div>

          {/* SOS Critical (locked ON) */}
          <div className="flex items-center justify-between gap-4 pb-3 border-b">
            <div className="flex-1">
              <div className="flex items-center gap-2">
                <p className="font-medium text-slate-800">SOS / emergency alerts</p>
                <Badge className="text-[10px] bg-red-100 text-red-700">Required</Badge>
              </div>
              <p className="text-xs text-slate-500 mt-0.5">Cannot be disabled for safety reasons</p>
            </div>
            <Toggle enabled={true} disabled />
          </div>

          {/* Digests */}
          <div className="flex items-center justify-between gap-4 pb-3 border-b">
            <div className="flex-1">
              <p className="font-medium text-slate-800">Daily safety digest</p>
              <p className="text-xs text-slate-500 mt-0.5">One summary email every morning at 8 AM</p>
            </div>
            <Toggle enabled={prefs.daily_digest} onChange={(v) => updatePref('daily_digest', v)} />
          </div>

          <div className="flex items-center justify-between gap-4">
            <div className="flex-1">
              <p className="font-medium text-slate-800">Weekly report</p>
              <p className="text-xs text-slate-500 mt-0.5">Journey, safety score, and incident trends every Monday</p>
            </div>
            <Toggle enabled={prefs.weekly_report} onChange={(v) => updatePref('weekly_report', v)} />
          </div>
        </CardContent>
      </Card>

      {/* Danger zone */}
      <Card data-testid="settings-danger" className="border-red-200">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-lg text-red-600">
            <LogOut className="w-5 h-5" />
            Session
          </CardTitle>
        </CardHeader>
        <CardContent>
          <Button onClick={handleLogout} variant="outline" className="text-red-600 border-red-300 hover:bg-red-50" data-testid="logout-btn">
            <LogOut className="w-4 h-4 mr-2" />
            Sign out
          </Button>
        </CardContent>
      </Card>
    </div>
  );
};

const FamilyDashboard = () => {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [sseConnected, setSseConnected] = useState(false);
  const [activeEmergency, setActiveEmergency] = useState(null);
  const [routeDeviation, setRouteDeviation] = useState(null);
  const [fallEvent, setFallEvent] = useState(null);
  const [wanderingEvent, setWanderingEvent] = useState(null);
  const [pickupEvent, setPickupEvent] = useState(null);
  const [voiceDistressEvent, setVoiceDistressEvent] = useState(null);
  const [safetyBrainEvent, setSafetyBrainEvent] = useState(null);
  const [rerouteSuggestion, setRerouteSuggestion] = useState(null);
  const [predictiveAlert, setPredictiveAlert] = useState(null);
  const [fakeCallData, setFakeCallData] = useState(null);
  const [fakeNotifData, setFakeNotifData] = useState(null);
  const [activeSOS, setActiveSOS] = useState(null);
  const [guardianAIAlert, setGuardianAIAlert] = useState(null);
  const eventSourceRef = useRef(null);
  
  // SSE event handlers - will be set by child components
  const eventHandlersRef = useRef({
    onIncidentCreated: null,
    onIncidentUpdated: null,
    onIncidentEscalated: null,
  });

  // Setup SSE connection
  useEffect(() => {
    // Request push permission and register token
    const setupPush = async () => {
      try {
        const token = await requestPushToken();
        if (token) {
          await api.post('/push/token', { token });
          console.log('Push token registered');
        }
      } catch (err) {
        console.warn('Push setup skipped:', err.message);
      }
    };
    setupPush();

    // Listen for foreground push messages
    const unsubPush = onForegroundMessage((payload) => {
      const { title, body } = payload.notification || {};
      toast.warning(title || 'NISCHINT Alert', { description: body });
    });

    const handleEvent = (eventType, data) => {
      console.log('SSE Event:', eventType, data);
      
      switch (eventType) {
        case 'connected':
          setSseConnected(true);
          console.log('SSE connected for guardian:', data.guardian_id);
          break;
        case 'incident_created':
          toast.error(`New incident: ${data.data?.incident_type || 'Alert'}`, {
            description: `Severity: ${data.data?.severity || 'unknown'}`,
          });
          eventHandlersRef.current.onIncidentCreated?.(data.data);
          break;
        case 'incident_updated':
          toast.info(`Incident updated: ${data.data?.status || 'changed'}`);
          eventHandlersRef.current.onIncidentUpdated?.(data.data);
          break;
        case 'incident_escalated':
          toast.warning(`Incident escalated: ${data.data?.incident_type || 'Alert'}`, {
            description: 'Immediate attention required!',
          });
          eventHandlersRef.current.onIncidentEscalated?.(data.data);
          break;
        case 'emergency_triggered':
          toast.error('EMERGENCY SOS TRIGGERED', {
            description: `Location: (${data.data?.lat?.toFixed(4)}, ${data.data?.lng?.toFixed(4)})`,
            duration: 30000,
          });
          setActiveEmergency(data.data);
          break;
        case 'emergency_location_update':
          setActiveEmergency(prev => prev ? { ...prev, lat: data.data?.lat, lng: data.data?.lng } : prev);
          break;
        case 'emergency_cancelled':
          toast.success('Emergency cancelled — user confirmed safe', { duration: 10000 });
          setActiveEmergency(null);
          break;
        case 'emergency_resolved':
          toast.info('Emergency resolved', { duration: 10000 });
          setActiveEmergency(null);
          break;
        case 'ping':
          // Keepalive, no action needed
          break;
        case 'route_warning':
          toast.warning('Route Warning: Minor deviation detected', {
            description: `${data.data?.distance_from_route_m?.toFixed(0) || '?'}m from route`,
            duration: 8000,
          });
          setRouteDeviation(data);
          break;
        case 'route_alert':
          toast.error('Route Alert: Unsafe deviation!', {
            description: `${data.data?.distance_from_route_m?.toFixed(0) || '?'}m from route — suggest reroute`,
            duration: 15000,
          });
          setRouteDeviation(data);
          break;
        case 'route_emergency':
          toast.error('ROUTE EMERGENCY: Critical deviation!', {
            description: `${data.data?.distance_from_route_m?.toFixed(0) || '?'}m from route — guardian alert triggered`,
            duration: 30000,
          });
          setRouteDeviation(data);
          break;
        case 'route_back_on_track':
          toast.success('Back on track: User returned to safe corridor', { duration: 5000 });
          setRouteDeviation(null);
          break;
        case 'fall_detected': {
          const conf = data.data?.confidence;
          const level = data.data?.marker_level;
          if (level === 'critical') {
            toast.error('FALL DETECTED (Critical Confidence)', {
              description: `Confidence: ${(conf * 100).toFixed(0)}% — User may be unresponsive`,
              duration: 30000,
            });
          } else if (level === 'high') {
            toast.error('Possible Fall Detected', {
              description: `Confidence: ${(conf * 100).toFixed(0)}% — Monitoring for response`,
              duration: 20000,
            });
          } else {
            toast.warning('Possible Fall Detected', {
              description: `Confidence: ${(conf * 100).toFixed(0)}%`,
              duration: 15000,
            });
          }
          setFallEvent(data.data);
          break;
        }
        case 'fall_resolved':
          toast.success('Fall Event Resolved — User confirmed safe', { duration: 8000 });
          setFallEvent(null);
          break;
        case 'fall_auto_sos':
          toast.error('FALL AUTO-SOS: User unresponsive — Emergency triggered!', {
            description: 'Silent SOS auto-triggered after fall detection',
            duration: 30000,
          });
          setFallEvent(prev => prev ? { ...prev, status: 'auto_sos' } : prev);
          setActiveEmergency(data.data);
          break;
        case 'wandering_detected':
          toast.warning('Wandering Detected', {
            description: `${data.data?.safe_zone_name || 'Zone'} — ${data.data?.distance_m?.toFixed(0) || '?'}m away (score: ${data.data?.wander_score?.toFixed(2) || '?'})`,
            duration: 20000,
          });
          setWanderingEvent(data.data);
          break;
        case 'wandering_escalated':
          toast.error('Wandering ESCALATED — User far from safe zone!', {
            description: `${data.data?.safe_zone_name || 'Zone'} — ${data.data?.distance_m?.toFixed(0) || '?'}m away`,
            duration: 30000,
          });
          setWanderingEvent({ ...data.data, escalated: true });
          break;
        case 'wandering_resolved':
          toast.success('Wandering Event Resolved', { duration: 5000 });
          setWanderingEvent(null);
          break;
        case 'pickup_scheduled':
          toast.info('Pickup Scheduled', {
            description: `${data.data?.authorized_person || 'Person'} at ${data.data?.location || 'location'}`,
            duration: 10000,
          });
          setPickupEvent({ ...data.data, type: 'scheduled' });
          break;
        case 'pickup_verified':
          toast.success('Pickup Verified!', {
            description: `${data.data?.authorized_person || 'Person'} confirmed at ${data.data?.location || 'location'}`,
            duration: 15000,
          });
          setPickupEvent({ ...data.data, type: 'verified' });
          break;
        case 'pickup_failed': {
          const reason = data.data?.reason || 'unknown';
          const reasonLabel = reason === 'invalid_code' ? 'Invalid Code' : reason === 'proximity_failed' ? 'Too Far' : reason === 'code_expired' ? 'Code Expired' : reason;
          toast.error(`Pickup Failed: ${reasonLabel}`, {
            description: `${data.data?.authorized_person || ''}${data.data?.distance_m ? ` (${data.data.distance_m.toFixed(0)}m away)` : ''}`,
            duration: 20000,
          });
          setPickupEvent({ ...data.data, type: 'failed' });
          break;
        }
        case 'voice_alert': {
          const vs = data.data;
          const isAutoSos = vs?.auto_sos;
          if (isAutoSos) {
            toast.error('VOICE DISTRESS — AUTO SOS TRIGGERED!', {
              description: `Keywords: ${(vs?.keywords || []).join(', ')} | Score: ${vs?.distress_score?.toFixed(2)}`,
              duration: 30000,
            });
          } else {
            toast.error('Voice Distress Alert', {
              description: `${vs?.scream_detected ? 'Scream detected. ' : ''}Keywords: ${(vs?.keywords || []).join(', ')} | Score: ${vs?.distress_score?.toFixed(2)}`,
              duration: 20000,
            });
          }
          setVoiceDistressEvent(vs);
          if (isAutoSos) setActiveEmergency(vs);
          break;
        }
        case 'voice_distress_resolved':
          toast.success('Voice Distress Resolved', { duration: 5000 });
          setVoiceDistressEvent(null);
          break;
        case 'safety_risk_alert': {
          const sb = data.data;
          const level = sb?.risk_level;
          const score = sb?.risk_score;
          const primary = sb?.primary_event;
          if (level === 'critical') {
            toast.error('CRITICAL SAFETY EVENT', {
              description: `Risk: ${(score * 100).toFixed(0)}% | Primary: ${primary} | Auto-SOS triggered`,
              duration: 30000,
            });
          } else if (level === 'dangerous') {
            toast.error('DANGEROUS Safety Alert', {
              description: `Risk: ${(score * 100).toFixed(0)}% | Primary: ${primary}`,
              duration: 20000,
            });
          } else {
            toast.warning('Safety Alert — Suspicious Activity', {
              description: `Risk: ${(score * 100).toFixed(0)}% | Primary: ${primary}`,
              duration: 15000,
            });
          }
          setSafetyBrainEvent(sb);
          break;
        }
        case 'safety_reroute_suggestion': {
          const rr = data.data;
          toast.warning('Safer Route Available', {
            description: `Risk: ${Math.round((rr?.risk_score || 0) * 100)}% | ${rr?.reason?.slice(0, 60)}`,
            duration: 20000,
          });
          setRerouteSuggestion(rr);
          break;
        }
        case 'safety_reroute_approved': {
          toast.success('Reroute Approved', {
            description: 'Route updated to safer path',
            duration: 10000,
          });
          setRerouteSuggestion(null);
          break;
        }
        case 'voice_verification_complete': {
          const vv = data.data;
          const vLevel = vv?.distress_level;
          if (vLevel === 'emergency' || vLevel === 'high_alert') {
            toast.error('Whisper Verified: DISTRESS CONFIRMED', {
              description: `Confidence: ${Math.round((vv?.whisper_confidence || 0) * 100)}% | "${vv?.transcript?.slice(0, 40) || '...'}"`,
              duration: 25000,
            });
          } else if (vv?.distress_detected) {
            toast.warning('Whisper: Possible Distress', {
              description: `Confidence: ${Math.round((vv?.whisper_confidence || 0) * 100)}% | ${vv?.phrases_found?.join(', ')?.slice(0, 50) || '...'}`,
              duration: 15000,
            });
          }
          // Update the voiceDistressEvent with verification data
          setVoiceDistressEvent(prev => prev ? { ...prev, ...vv, whisper_verified: true } : vv);
          break;
        }
        case 'predictive_safety_alert': {
          const pa = data.data;
          const paLevel = pa?.alert_level;
          if (paLevel === 'high') {
            toast.error('Predictive Alert: HIGH RISK Pattern Detected', {
              description: `Confidence: ${pa?.confidence_pct || 0}% | ${pa?.narrative?.slice(0, 80) || '...'}`,
              duration: 25000,
            });
          } else if (paLevel === 'medium') {
            toast.warning('Predictive Alert: Emerging Risk Pattern', {
              description: `Confidence: ${pa?.confidence_pct || 0}% | ${pa?.patterns?.[0]?.type?.replace(/_/g, ' ') || 'behavioral anomaly'}`,
              duration: 15000,
            });
          }
          setPredictiveAlert(pa);
          break;
        }
        case 'fake_call_incoming': {
          const fc = data.data;
          setFakeCallData(fc);
          break;
        }
        case 'fake_notification_incoming': {
          const fn = data.data;
          setFakeNotifData(fn);
          break;
        }
        case 'sos_triggered': {
          const sos = data.data;
          setActiveSOS(sos);
          toast.error('SOS TRIGGERED', {
            description: `Silent alert via ${sos.trigger_type}. Chain sequence initiated.`,
            duration: 20000,
          });
          // Auto-chain: trigger notification after delay
          if (sos.chain?.notification) {
            setTimeout(() => {
              setFakeNotifData({
                notification_id: `chain-${Date.now()}`,
                title: sos.chain.notification.title,
                message: sos.chain.notification.message,
                category: 'Work',
                icon_style: 'calendar',
              });
            }, (sos.chain.notification.delay_seconds || 10) * 1000);
          }
          // Auto-chain: trigger fake call after delay
          if (sos.chain?.call) {
            setTimeout(() => {
              setFakeCallData({
                call_id: `chain-${Date.now()}`,
                caller_name: sos.chain.call.caller_name,
                caller_label: 'Work',
                ringtone_style: 'professional',
              });
            }, (sos.chain.call.delay_seconds || 40) * 1000);
          }
          break;
        }
        case 'sos_resolved': {
          setActiveSOS(prev => prev ? { ...prev, status: 'resolved' } : null);
          toast.success('SOS Resolved', { description: 'Emergency alert cancelled.' });
          break;
        }
        case 'guardian_ai_alert': {
          const ga = data.data;
          setGuardianAIAlert(ga);
          const gaLevel = ga.risk_level;
          if (gaLevel === 'critical' || gaLevel === 'high') {
            toast.error(`Guardian AI: ${gaLevel.toUpperCase()} RISK detected`, {
              description: `Action: ${ga.recommended_action?.replace(/_/g, ' ')} | Confidence: ${Math.round((ga.confidence || 0) * 100)}%`,
              duration: 20000,
            });
          } else if (gaLevel === 'moderate') {
            toast.warning('Guardian AI: Elevated risk pattern', {
              description: `Score: ${Math.round((ga.risk_score || 0) * 100)}% | ${ga.risk_factors?.[0]?.type?.replace(/_/g, ' ') || 'pattern detected'}`,
              duration: 15000,
            });
          }
          break;
        }
        case 'voice_trigger_activated': {
          const vt = data.data;
          const vtAction = vt?.linked_action;
          toast.success(`Voice Trigger: "${vt?.matched_phrase}" activated`, {
            description: `Action: ${vtAction === 'sos' ? 'SOS Silent Mode' : vtAction === 'fake_call' ? 'Escape Call' : 'Escape Notification'} | ${Math.round((vt?.confidence || 0) * 100)}% confidence`,
            duration: 10000,
          });
          // Auto-trigger linked action via SSE
          if (vtAction === 'fake_call' && vt?.action_result?.config) {
            setFakeCallData({
              call_id: `voice-${Date.now()}`,
              caller_name: vt.action_result.config.caller_name || 'Boss',
              caller_label: 'Voice Trigger',
              ringtone_style: 'professional',
            });
          } else if (vtAction === 'fake_notification' && vt?.action_result?.config) {
            setFakeNotifData({
              notification_id: `voice-${Date.now()}`,
              title: vt.action_result.config.title || 'Urgent',
              message: vt.action_result.config.message || 'Check your phone',
              category: vt.action_result.config.category || 'Work',
              icon_style: 'calendar',
            });
          } else if (vtAction === 'sos') {
            setActiveSOS({
              sos_id: `voice-${Date.now()}`,
              trigger_type: 'voice',
              status: 'active',
            });
          }
          break;
        }
        case 'risk_update': {
          // Real-time per-child risk pushed by the backend
          // `risk_emitter`. Replaces the steady-state /live/risk poll.
          //
          // Dedup contract:
          //   • `emit_key = "{child_id}:{version}"` — globally unique
          //     even across server restarts / SSE reconnects. Hard
          //     idempotency.
          //   • `version` — per-child monotonic. Catches out-of-order
          //     delivery when the emit_key cache has been pruned.
          const childId = String(data?.child_id || '');
          if (!childId) break;
          const emitKey = String(data?.emit_key || '');
          if (emitKey && _seenRiskEmitKeys.has(emitKey)) break;
          const incoming = Number(data?.version) || 0;
          if (emitKey) {
            _seenRiskEmitKeys.add(emitKey);
            if (_seenRiskEmitKeys.size > 500) {
              const it = _seenRiskEmitKeys.values();
              for (let i = 0; i < 100; i++) _seenRiskEmitKeys.delete(it.next().value);
            }
          }
          setLiveRisk((prev) => {
            const cur = prev?.[childId];
            const prevVersion = Number(cur?.version) || 0;
            if (incoming > 0 && prevVersion > incoming) return prev;
            return {
              ...(prev || {}),
              [childId]: {
                child_id:    childId,
                child_name:  data.child_name,
                lat:         data.lat,
                lng:         data.lng,
                risk:        data.risk_level || data.risk,
                score:       data.score,
                factors:     data.factors || [],
                speed_kmh:   data.speed_kmh || 0,
                last_updated: data.last_updated || new Date().toISOString(),
                version:     incoming,
              },
            };
          });
          break;
        }
        default:
          console.log('Unknown SSE event:', eventType);
      }
    };
    
    const handleError = (error) => {
      console.error('SSE error:', error);
    };
    
    eventSourceRef.current = createEventSource(handleEvent, handleError, (status) => {
      setSseConnected(status === 'connected');
    });
    
    return () => {
      eventSourceRef.current?.close();
      setSseConnected(false);
    };
  }, []);

  const handleLogout = () => {
    eventSourceRef.current?.close();
    logout();
    toast.success('Logged out successfully');
    navigate('/login');
  };
  
  // Register event handlers from child components
  const registerEventHandler = useCallback((type, handler) => {
    eventHandlersRef.current[type] = handler;
  }, []);

  return (
    <div className="flex min-h-screen bg-slate-50" data-testid="family-dashboard">
      <Sidebar onLogout={handleLogout} connected={sseConnected} user={user} />
      <main className="flex-1 p-8">
        {activeEmergency && (
          <div className="mb-6 rounded-xl bg-red-600 p-4 text-white shadow-lg animate-pulse" data-testid="emergency-alert-banner">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-white/20">
                <Zap className="h-5 w-5" />
              </div>
              <div className="flex-1">
                <p className="text-sm font-black tracking-wider">EMERGENCY SOS ACTIVE</p>
                <p className="text-xs text-white/80">
                  Trigger: {activeEmergency.trigger_source} | Location: ({activeEmergency.lat?.toFixed(4)}, {activeEmergency.lng?.toFixed(4)})
                </p>
              </div>
              <div className="text-right text-xs text-white/70">
                <p>Live tracking</p>
                <p className="font-semibold text-white">{activeEmergency.event_id?.slice(0, 8)}...</p>
              </div>
            </div>
          </div>
        )}
        {safetyBrainEvent && safetyBrainEvent.risk_level !== 'normal' && !activeEmergency && (
          <div className={`mb-6 rounded-xl p-4 text-white shadow-lg ${
            safetyBrainEvent.risk_level === 'critical' ? 'bg-red-600 animate-pulse'
            : safetyBrainEvent.risk_level === 'dangerous' ? 'bg-orange-600'
            : 'bg-amber-600'
          }`} data-testid="safety-brain-banner">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-white/20">
                <Brain className="h-5 w-5" />
              </div>
              <div className="flex-1">
                <p className="text-sm font-black tracking-wider">
                  {safetyBrainEvent.risk_level === 'critical' ? 'CRITICAL' : safetyBrainEvent.risk_level === 'dangerous' ? 'DANGEROUS' : 'SUSPICIOUS'} SAFETY EVENT
                </p>
                <p className="text-xs text-white/80">
                  Score: {Math.round(safetyBrainEvent.risk_score * 100)}% | Primary: {safetyBrainEvent.primary_event} | Signals: {Object.entries(safetyBrainEvent.signals || {}).filter(([,v]) => v > 0).map(([k]) => k).join(', ')}
                </p>
              </div>
              <button onClick={() => setSafetyBrainEvent(null)} className="text-white/70 hover:text-white">
                <XCircle className="h-5 w-5" />
              </button>
            </div>
          </div>
        )}
        <Routes>
          <Route index element={<Overview />} />
          <Route path="live" element={<FamilyLivePage />} />
          <Route path="safety" element={<GuardianSafetyDashboard />} />
          <Route path="safety-score" element={<SafetyScoreDashboard />} />
          <Route path="emergency-map" element={<EmergencyMap activeEmergency={activeEmergency} fallEvent={fallEvent} wanderingEvent={wanderingEvent} pickupEvent={pickupEvent} voiceDistressEvent={voiceDistressEvent} safetyBrainEvent={safetyBrainEvent} rerouteSuggestion={rerouteSuggestion} onRerouteAction={(action, id) => {
            if (action === 'dismiss') setRerouteSuggestion(null);
          }} />} />
          <Route path="safety-brain" element={<SafetyBrainDashboard predictiveAlert={predictiveAlert} />} />
          <Route path="escape-call" element={<FakeCallPage onIncomingCall={(d) => setFakeCallData(d)} />} />
          <Route path="escape-notification" element={<FakeNotificationPage onNotification={(d) => setFakeNotifData(d)} />} />
          <Route path="sos" element={<SOSPage activeSOS={activeSOS} onTriggerSOS={(d) => setActiveSOS(d)} />} />
          <Route path="guardian-ai" element={<GuardianAIPage latestAlert={guardianAIAlert} />} />
          <Route path="voice-trigger" element={<VoiceTriggerPage onVoiceTrigger={(data) => {
            if (data.linked_action === 'fake_call' && data.action_result?.config) {
              setFakeCallData({ call_id: `voice-${Date.now()}`, caller_name: data.action_result.config.caller_name || 'Boss', caller_label: 'Voice Trigger', ringtone_style: 'professional' });
            } else if (data.linked_action === 'fake_notification' && data.action_result?.config) {
              setFakeNotifData({ notification_id: `voice-${Date.now()}`, title: data.action_result.config.title || 'Urgent', message: data.action_result.config.message || 'Check your phone', category: data.action_result.config.category || 'Work', icon_style: 'calendar' });
            } else if (data.linked_action === 'sos') {
              setActiveSOS({ sos_id: `voice-${Date.now()}`, trigger_type: 'voice', status: 'active' });
            }
          }} />} />
          <Route path="route-monitor" element={<RouteMonitorPage routeDeviation={routeDeviation} onDeviationHandled={() => setRouteDeviation(null)} />} />
          <Route path="incidents" element={<IncidentsPage registerEventHandler={registerEventHandler} />} />
          <Route path="metrics" element={<GuardianMetrics />} />
          <Route path="seniors" element={<SeniorsPage />} />
          <Route path="safety-zones" element={<SafetyZonesPage />} />
          <Route path="settings" element={<SettingsPage />} />
        </Routes>
      </main>

      {/* Fake Call Screen Overlay */}
      {fakeCallData && (
        <FakeCallScreen callData={fakeCallData} onClose={() => setFakeCallData(null)} />
      )}

      {/* Fake Notification Overlay */}
      {fakeNotifData && (
        <NotificationOverlay data={fakeNotifData} onClose={() => setFakeNotifData(null)} />
      )}
    </div>
  );
};

export default FamilyDashboard;
