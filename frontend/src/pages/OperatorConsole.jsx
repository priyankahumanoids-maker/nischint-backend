import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Routes, Route, NavLink, useNavigate, useParams } from 'react-router-dom';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Input } from '../components/ui/input';
import { Avatar, AvatarFallback } from '../components/ui/avatar';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../components/ui/table';
import { useAuth } from '../contexts/AuthContext';
import api from '../api';
import { operatorApi, createEventSource } from '../api';
import { toast } from 'sonner';
import { 
  Shield, LayoutDashboard, Users, AlertCircle, Settings,
  Activity, Bell, Search, Clock, CheckCircle, XCircle, 
  Filter, LogOut, Headphones, AlertTriangle, Loader2, RefreshCw,
  Mail, MessageSquare, Zap, Gauge, SkullIcon, PauseCircle, RotateCcw, Send, Settings2,
  Wifi, Brain, MapPin, Navigation, Phone, Inbox, Globe, Moon, Star
} from 'lucide-react';
import HealthRulesPage from './HealthRulesPage';
import SimulationLab from './SimulationLab';
import EscalationAnalytics from './EscalationAnalytics';
import { IncidentMetricTrends } from '../components/MetricSparkline';
import FleetHealthTrends from '../components/FleetHealthTrends';
import { PredictiveAlertsPanel } from '../components/PredictiveAlertsPanel';
import { IncidentNarrative } from '../components/IncidentNarrative';
import { FleetSafetyScore } from '../components/FleetSafetyScore';
import { LocationRiskHeatmap } from '../components/LocationRiskHeatmap';
import { RouteSafetyIntelligence } from '../components/RouteSafetyIntelligence';
import { IncidentReplayViewer } from '../components/IncidentReplayViewer';
import CommandCenter from './CommandCenter';
import DeviceHealthPage from './DeviceHealthPage';
import EscalationDashboard from './EscalationDashboard';
import RiskLearningDashboard from './RiskLearningDashboard';
import HumanActivityRiskPage from './HumanActivityRiskPage';
import PatrolAIDashboard from './PatrolAIDashboard';
import CityHeatmapDashboard from './CityHeatmapDashboard';
import SafeZoneDashboard from './SafeZoneDashboard';
import NightGuardianDashboard from './NightGuardianDashboard';
import SafeRouteDashboard from './SafeRouteDashboard';
import GuardianModeDashboard from './GuardianModeDashboard';
import PredictiveAlertDashboard from './PredictiveAlertDashboard';
import SafetyScoreDashboard from './SafetyScoreDashboard';

const severityColor = (s) => {
  switch (s) {
    case 'critical': return 'bg-red-100 text-red-700';
    case 'high': return 'bg-orange-100 text-orange-700';
    case 'medium': return 'bg-yellow-100 text-yellow-700';
    default: return 'bg-slate-100 text-slate-700';
  }
};

const statusColor = (s) => {
  switch (s) {
    case 'open': return 'bg-red-100 text-red-700';
    case 'acknowledged': return 'bg-blue-100 text-blue-700';
    case 'resolved': return 'bg-green-100 text-green-700';
    case 'false_alarm': return 'bg-slate-100 text-slate-600';
    default: return 'bg-slate-100 text-slate-700';
  }
};

const timeAgo = (date) => {
  const diff = (Date.now() - new Date(date).getTime()) / 1000;
  if (diff < 60) return `${Math.floor(diff)}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
};

const SSE_STATUS_MAP = {
  connected: { color: 'bg-green-500', label: 'Live' },
  connecting: { color: 'bg-yellow-500 animate-pulse', label: 'Connecting' },
  reconnecting: { color: 'bg-yellow-500 animate-pulse', label: 'Reconnecting' },
  disconnected: { color: 'bg-red-500', label: 'Disconnected' },
};

const Sidebar = ({ stats, onLogout, sseStatus = 'disconnected', user }) => {
  const sse = SSE_STATUS_MAP[sseStatus] || SSE_STATUS_MAP.disconnected;
  const displayName = user?.full_name || user?.email || 'Operator';
  return (
  <aside className="w-64 bg-slate-900 text-white min-h-screen p-6 flex flex-col">
    <div className="flex items-center gap-3 mb-10">
      <div className="w-10 h-10 bg-amber-500 rounded-lg flex items-center justify-center">
        <Headphones className="w-6 h-6" />
      </div>
      <div>
        <h1 className="font-bold text-lg">NISCHINT</h1>
        <p className="text-xs text-slate-400">Operator Console</p>
      </div>
    </div>

    <div className="flex items-center gap-2 mb-6 px-2" data-testid="op-sse-status">
      <span className={`w-2 h-2 rounded-full ${sse.color}`} />
      <span className="text-xs text-slate-400">{sse.label}</span>
    </div>

    <nav className="flex-1 space-y-2">
      <NavLink to="/operator-dashboard"
        className={({ isActive }) => `flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${isActive ? 'bg-amber-600 text-white' : 'text-slate-400 hover:bg-slate-800'}`}
        data-testid="op-nav-dispatch"
      >
        <Headphones className="w-5 h-5" />
        Incident Dispatch
      </NavLink>
      <NavLink to="/caregiver"
        className={({ isActive }) => `flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${isActive ? 'bg-emerald-600 text-white' : 'text-slate-400 hover:bg-slate-800'}`}
        data-testid="op-nav-caregiver"
      >
        <Users className="w-5 h-5" />
        Caregiver View
      </NavLink>
      <NavLink to="/replay"
        className={({ isActive }) => `flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${isActive ? 'bg-cyan-600 text-white' : 'text-slate-400 hover:bg-slate-800'}`}
        data-testid="op-nav-replay"
      >
        <Headphones className="w-5 h-5" />
        Journey Replay
      </NavLink>
      <NavLink to="/operator/command-center"
        className={({ isActive }) => `flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${isActive ? 'bg-amber-600 text-white' : 'text-slate-400 hover:bg-slate-800'}`}
        data-testid="op-nav-command-center"
      >
        <Brain className="w-5 h-5" />
        Command Center
      </NavLink>
      <NavLink to="/operator" end
        className={({ isActive }) => `flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${isActive ? 'bg-amber-600 text-white' : 'text-slate-400 hover:bg-slate-800'}`}
        data-testid="op-nav-dashboard"
      >
        <LayoutDashboard className="w-5 h-5" />
        Dashboard
      </NavLink>
      <NavLink to="/operator/incidents"
        className={({ isActive }) => `flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${isActive ? 'bg-amber-600 text-white' : 'text-slate-400 hover:bg-slate-800'}`}
        data-testid="op-nav-incidents"
      >
        <AlertCircle className="w-5 h-5" />
        Incidents
        {stats?.open_incidents > 0 && (
          <Badge className="ml-auto bg-red-500">{stats.open_incidents}</Badge>
        )}
      </NavLink>
      <NavLink to="/operator/device-health"
        className={({ isActive }) => `flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${isActive ? 'bg-amber-600 text-white' : 'text-slate-400 hover:bg-slate-800'}`}
        data-testid="op-nav-device-health"
      >
        <Activity className="w-5 h-5" />
        Device Health
      </NavLink>
      <NavLink to="/operator/location-risk"
        className={({ isActive }) => `flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${isActive ? 'bg-amber-600 text-white' : 'text-slate-400 hover:bg-slate-800'}`}
        data-testid="op-nav-location-risk"
      >
        <MapPin className="w-5 h-5" />
        Location Risk
      </NavLink>
      <NavLink to="/operator/route-safety"
        className={({ isActive }) => `flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${isActive ? 'bg-amber-600 text-white' : 'text-slate-400 hover:bg-slate-800'}`}
        data-testid="op-nav-route-safety"
      >
        <Navigation className="w-5 h-5" />
        Route Safety
      </NavLink>
      <NavLink to="/operator/health-rules"
        className={({ isActive }) => `flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${isActive ? 'bg-amber-600 text-white' : 'text-slate-400 hover:bg-slate-800'}`}
        data-testid="op-nav-health-rules"
      >
        <Settings2 className="w-5 h-5" />
        Health Rules
      </NavLink>
      <NavLink to="/operator/simulation"
        className={({ isActive }) => `flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${isActive ? 'bg-amber-600 text-white' : 'text-slate-400 hover:bg-slate-800'}`}
        data-testid="op-nav-simulation"
      >
        <Zap className="w-5 h-5" />
        Simulation Lab
      </NavLink>
      <NavLink to="/operator/escalation-analytics"
        className={({ isActive }) => `flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${isActive ? 'bg-amber-600 text-white' : 'text-slate-400 hover:bg-slate-800'}`}
        data-testid="op-nav-escalation-analytics"
      >
        <Gauge className="w-5 h-5" />
        Safety Ops
      </NavLink>
      <NavLink to="/operator/escalation"
        className={({ isActive }) => `flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${isActive ? 'bg-amber-600 text-white' : 'text-slate-400 hover:bg-slate-800'}`}
        data-testid="op-nav-escalation"
      >
        <Shield className="w-5 h-5" />
        Escalation AI
      </NavLink>
      <NavLink to="/operator/risk-learning"
        className={({ isActive }) => `flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${isActive ? 'bg-amber-600 text-white' : 'text-slate-400 hover:bg-slate-800'}`}
        data-testid="op-nav-risk-learning"
      >
        <Brain className="w-5 h-5" />
        Risk Learning
      </NavLink>
      <NavLink to="/operator/activity-risk"
        className={({ isActive }) => `flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${isActive ? 'bg-amber-600 text-white' : 'text-slate-400 hover:bg-slate-800'}`}
        data-testid="op-nav-activity-risk"
      >
        <Users className="w-5 h-5" />
        Activity Risk
      </NavLink>
      <NavLink to="/operator/patrol-ai"
        className={({ isActive }) => `flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${isActive ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:bg-slate-800'}`}
        data-testid="op-nav-patrol-ai"
      >
        <Navigation className="w-5 h-5" />
        Patrol AI
      </NavLink>
      <NavLink to="/operator/city-heatmap"
        className={({ isActive }) => `flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${isActive ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:bg-slate-800'}`}
        data-testid="op-nav-city-heatmap"
      >
        <Globe className="w-5 h-5" />
        City Heatmap
      </NavLink>
      <NavLink to="/operator/safe-zones"
        className={({ isActive }) => `flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${isActive ? 'bg-emerald-600 text-white' : 'text-slate-400 hover:bg-slate-800'}`}
        data-testid="op-nav-safe-zones"
      >
        <Shield className="w-5 h-5" />
        Safe Zones
      </NavLink>
      <NavLink to="/operator/night-guardian"
        className={({ isActive }) => `flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${isActive ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:bg-slate-800'}`}
        data-testid="op-nav-night-guardian"
      >
        <Moon className="w-5 h-5" />
        Night Guardian
      </NavLink>
      <NavLink to="/operator/safe-route"
        className={({ isActive }) => `flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${isActive ? 'bg-cyan-600 text-white' : 'text-slate-400 hover:bg-slate-800'}`}
        data-testid="op-nav-safe-route"
      >
        <Navigation className="w-5 h-5" />
        Safe Route AI
      </NavLink>
      <NavLink to="/operator/guardian-mode"
        className={({ isActive }) => `flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${isActive ? 'bg-pink-600 text-white' : 'text-slate-400 hover:bg-slate-800'}`}
        data-testid="op-nav-guardian-mode"
      >
        <Users className="w-5 h-5" />
        Guardian Mode
      </NavLink>
      <NavLink to="/operator/predictive-alerts"
        className={({ isActive }) => `flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${isActive ? 'bg-amber-600 text-white' : 'text-slate-400 hover:bg-slate-800'}`}
        data-testid="op-nav-predictive-alerts"
      >
        <AlertTriangle className="w-5 h-5" />
        Predictive Alerts
      </NavLink>
      <NavLink to="/operator/safety-score"
        className={({ isActive }) => `flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${isActive ? 'bg-amber-600 text-white' : 'text-slate-400 hover:bg-slate-800'}`}
        data-testid="op-nav-safety-score"
      >
        <Star className="w-5 h-5" />
        Safety Score
      </NavLink>
      <NavLink to="/operator/settings"
        className={({ isActive }) => `flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${isActive ? 'bg-amber-600 text-white' : 'text-slate-400 hover:bg-slate-800'}`}
        data-testid="op-nav-settings"
      >
        <Settings className="w-5 h-5" />
        Settings
      </NavLink>
    </nav>

    <div className="pt-6 border-t border-slate-700">
      <div className="flex items-center gap-3 mb-4">
        <Avatar className="w-10 h-10">
          <AvatarFallback className="bg-amber-600">{displayName[0].toUpperCase()}</AvatarFallback>
        </Avatar>
        <div className="overflow-hidden">
          <p className="font-medium text-sm truncate" data-testid="op-user-display-name">{displayName}</p>
          {user?.full_name && <p className="text-xs text-slate-400 truncate">{user?.email}</p>}
          {!user?.full_name && <p className="text-xs text-slate-400">On Duty</p>}
        </div>
      </div>
      <Button variant="ghost" className="w-full justify-start text-slate-400 hover:text-white" onClick={onLogout} data-testid="op-logout">
        <LogOut className="w-5 h-5 mr-3" />
        Sign Out
      </Button>
    </div>
  </aside>
  );
};

const jobStatusConfig = {
  pending:     { label: 'Pending',     color: 'bg-yellow-500', textColor: 'text-yellow-700', bgLight: 'bg-yellow-50', icon: PauseCircle },
  retrying:    { label: 'Retrying',    color: 'bg-orange-500', textColor: 'text-orange-700', bgLight: 'bg-orange-50', icon: RotateCcw },
  sent:        { label: 'Sent',        color: 'bg-emerald-500', textColor: 'text-emerald-700', bgLight: 'bg-emerald-50', icon: Send },
  dead_letter: { label: 'Dead Letter', color: 'bg-red-600',    textColor: 'text-red-700',    bgLight: 'bg-red-50',     icon: SkullIcon },
  cancelled:   { label: 'Cancelled',   color: 'bg-slate-400',  textColor: 'text-slate-600',  bgLight: 'bg-slate-50',   icon: XCircle },
};

const channelIcon = { email: Mail, sms: MessageSquare, push: Zap };

const DeliveryHealth = ({ deliveryStats, loading }) => {
  if (loading || !deliveryStats) return null;

  const { totals, by_channel, throughput_per_minute, window_minutes } = deliveryStats;
  const totalJobs = Object.values(totals).reduce((a, b) => a + b, 0);
  const channels = Object.keys(by_channel);

  return (
    <div className="space-y-4" data-testid="delivery-health">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold text-slate-800 flex items-center gap-2">
          <Activity className="w-5 h-5 text-amber-500" />
          Delivery Health
          {window_minutes && <span className="text-xs font-normal text-slate-400 ml-1">(last {window_minutes}min)</span>}
          <span className="relative flex h-2 w-2 ml-1" data-testid="delivery-health-live">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
            <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
          </span>
        </h3>
        {throughput_per_minute !== null && throughput_per_minute !== undefined && (
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-slate-900 text-white text-sm font-mono" data-testid="throughput-rate">
            <Gauge className="w-4 h-4 text-amber-400" />
            {throughput_per_minute} msg/min
          </div>
        )}
      </div>

      {/* Status totals bar */}
      <div className="grid grid-cols-5 gap-3">
        {['pending', 'retrying', 'sent', 'dead_letter', 'cancelled'].map((st) => {
          const cfg = jobStatusConfig[st];
          const Icon = cfg.icon;
          const count = totals[st] || 0;
          return (
            <Card key={st} className={`border-0 ${cfg.bgLight}`} data-testid={`delivery-stat-${st}`}>
              <CardContent className="p-4 flex items-center gap-3">
                <div className={`w-9 h-9 rounded-lg ${cfg.color} flex items-center justify-center`}>
                  <Icon className="w-4 h-4 text-white" />
                </div>
                <div>
                  <p className="text-2xl font-bold text-slate-800">{count}</p>
                  <p className="text-xs text-slate-500">{cfg.label}</p>
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>

      {/* Channel breakdown table */}
      {channels.length > 0 && (
        <Card className="border border-slate-200">
          <CardContent className="pt-4 pb-2 px-4">
            <Table>
              <TableHeader>
                <TableRow className="border-b border-slate-100">
                  <TableHead className="text-xs uppercase tracking-wider text-slate-500 w-28">Channel</TableHead>
                  {['sent', 'pending', 'retrying', 'dead_letter', 'cancelled'].map(st => (
                    <TableHead key={st} className="text-xs uppercase tracking-wider text-slate-500 text-right">
                      {jobStatusConfig[st].label}
                    </TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {['email', 'sms', 'push'].map((ch) => {
                  const data = by_channel[ch];
                  if (!data) return null;
                  const ChIcon = channelIcon[ch] || Activity;
                  return (
                    <TableRow key={ch} className="border-b border-slate-50" data-testid={`delivery-channel-${ch}`}>
                      <TableCell className="font-medium text-slate-700 flex items-center gap-2">
                        <ChIcon className="w-4 h-4 text-slate-400" />
                        {ch.toUpperCase()}
                      </TableCell>
                      {['sent', 'pending', 'retrying', 'dead_letter', 'cancelled'].map(st => (
                        <TableCell key={st} className="text-right tabular-nums">
                          <span className={`${(data[st] || 0) > 0 && st === 'dead_letter' ? 'text-red-600 font-semibold' : 'text-slate-600'}`}>
                            {data[st] || 0}
                          </span>
                        </TableCell>
                      ))}
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      {totalJobs === 0 && (
        <Card className="border-dashed border-2 border-slate-200">
          <CardContent className="p-8 text-center">
            <Send className="w-8 h-8 text-slate-300 mx-auto mb-2" />
            <p className="text-slate-400 text-sm">No notification jobs in this window</p>
          </CardContent>
        </Card>
      )}
    </div>
  );
};

const Dashboard = ({ stats, falseMetrics, incidents, deliveryStats, loading, onRefresh }) => {
  if (loading) {
    return <div className="flex items-center justify-center h-64"><Loader2 className="w-8 h-8 animate-spin text-amber-500" /></div>;
  }

  const openIncidents = incidents.filter(i => i.status === 'open');

  return (
    <div className="space-y-6" data-testid="operator-dashboard">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold text-slate-800">Dashboard</h2>
        <Button variant="outline" size="sm" onClick={onRefresh} data-testid="op-refresh">
          <RefreshCw className="w-4 h-4 mr-2" /> Refresh
        </Button>
      </div>

      {stats && (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <Card className="bg-gradient-to-br from-red-500 to-red-600 text-white border-0">
            <CardContent className="p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-red-100 text-sm">Open Incidents</p>
                  <p className="text-3xl font-bold" data-testid="op-stat-open">{stats.open_incidents}</p>
                </div>
                <AlertCircle className="w-10 h-10 text-red-200" />
              </div>
            </CardContent>
          </Card>
          <Card className="bg-gradient-to-br from-amber-500 to-amber-600 text-white border-0">
            <CardContent className="p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-amber-100 text-sm">Escalated</p>
                  <p className="text-3xl font-bold" data-testid="op-stat-escalated">{stats.escalated_incidents}</p>
                </div>
                <AlertTriangle className="w-10 h-10 text-amber-200" />
              </div>
            </CardContent>
          </Card>
          <Card className="bg-gradient-to-br from-blue-500 to-blue-600 text-white border-0">
            <CardContent className="p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-blue-100 text-sm">Total Seniors</p>
                  <p className="text-3xl font-bold" data-testid="op-stat-seniors">{stats.total_seniors}</p>
                </div>
                <Users className="w-10 h-10 text-blue-200" />
              </div>
            </CardContent>
          </Card>
          <Card className="bg-gradient-to-br from-green-500 to-green-600 text-white border-0">
            <CardContent className="p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-green-100 text-sm">Guardians</p>
                  <p className="text-3xl font-bold" data-testid="op-stat-guardians">{stats.total_guardians}</p>
                </div>
                <Shield className="w-10 h-10 text-green-200" />
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* False Alarm Metrics */}
      {falseMetrics && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4" data-testid="false-alarm-metrics">
          <Card className="border-l-4 border-l-rose-500">
            <CardContent className="p-5">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs font-medium text-slate-500 uppercase tracking-wide">False Alarms</p>
                  <p className="text-2xl font-bold text-slate-800" data-testid="fa-count">{falseMetrics.false_alarms}</p>
                </div>
                <XCircle className="w-8 h-8 text-rose-400" />
              </div>
            </CardContent>
          </Card>
          <Card className="border-l-4 border-l-amber-500">
            <CardContent className="p-5">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs font-medium text-slate-500 uppercase tracking-wide">False Alarm Rate</p>
                  <p className="text-2xl font-bold text-slate-800" data-testid="fa-rate">{falseMetrics.false_alarm_rate_percent}%</p>
                </div>
                <Activity className="w-8 h-8 text-amber-400" />
              </div>
            </CardContent>
          </Card>
          <Card className="border-l-4 border-l-indigo-500">
            <CardContent className="p-5">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs font-medium text-slate-500 uppercase tracking-wide">Escalated False Alarms</p>
                  <p className="text-2xl font-bold text-slate-800" data-testid="fa-escalated">{falseMetrics.escalated_false_alarms}</p>
                </div>
                <AlertTriangle className="w-8 h-8 text-indigo-400" />
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Delivery Health */}
      <DeliveryHealth deliveryStats={deliveryStats} loading={loading} />

      {/* Fleet Health Trends */}
      <FleetHealthTrends />

      {/* Fleet Safety Index */}
      <FleetSafetyScore />

      {/* Predictive Alerts */}
      <PredictiveAlertsPanel />

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <AlertCircle className="w-5 h-5 text-red-500" />
            Open Incidents ({openIncidents.length})
          </CardTitle>
          <CardDescription>Requires immediate attention</CardDescription>
        </CardHeader>
        <CardContent>
          {openIncidents.length === 0 ? (
            <p className="text-slate-400 text-center py-8">No open incidents</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Type</TableHead>
                  <TableHead>Severity</TableHead>
                  <TableHead>Level</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Created</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {openIncidents.slice(0, 10).map((inc) => (
                  <TableRow key={inc.id} className={
                    inc.escalation_level === 3 ? 'bg-red-50 border-l-4 border-l-red-600' :
                    inc.escalation_level === 2 ? 'bg-amber-50 border-l-4 border-l-amber-500' : ''
                  }>
                    <TableCell className="font-medium">
                      {inc.escalation_level === 3 && <AlertTriangle className="w-4 h-4 text-red-600 inline mr-1" />}
                      {inc.incident_type.replace(/_/g, ' ')}
                    </TableCell>
                    <TableCell><Badge className={severityColor(inc.severity)}>{inc.severity}</Badge></TableCell>
                    <TableCell>
                      <Badge className={
                        inc.escalation_level === 3 ? 'bg-red-600 text-white' :
                        inc.escalation_level === 2 ? 'bg-amber-500 text-white' :
                        'bg-slate-400 text-white'
                      }>L{inc.escalation_level}</Badge>
                    </TableCell>
                    <TableCell><Badge className={statusColor(inc.status)}>{inc.status}</Badge></TableCell>
                    <TableCell className="text-slate-500">{timeAgo(inc.created_at)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
};

const IncidentsPage = ({ incidents, loading, onRefresh }) => {
  const [filter, setFilter] = useState({ status: '', severity: '' });
  const [search, setSearch] = useState('');
  const [expandedId, setExpandedId] = useState(null);
  const [incJobs, setIncJobs] = useState([]);
  const [jobsLoading, setJobsLoading] = useState(false);
  const [actionLoading, setActionLoading] = useState(null);

  const filtered = incidents.filter(i => {
    if (filter.status && i.status !== filter.status) return false;
    if (filter.severity && i.severity !== filter.severity) return false;
    if (search && !i.incident_type.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  const fetchIncidentJobs = async (incidentId) => {
    setJobsLoading(true);
    try {
      const { data } = await api.get(`/operator/incidents/${incidentId}/notification-jobs`);
      setIncJobs(data);
    } catch {
      toast.error('Failed to load notification jobs');
    } finally {
      setJobsLoading(false);
    }
  };

  const toggleJobs = async (incidentId) => {
    if (expandedId === incidentId) {
      setExpandedId(null);
      setIncJobs([]);
      return;
    }
    setExpandedId(incidentId);
    await fetchIncidentJobs(incidentId);
  };

  const handleRetry = async (jobId) => {
    setActionLoading(jobId);
    try {
      await operatorApi.retryNotificationJob(jobId);
      toast.success("Notification job queued for retry");
      if (expandedId) await fetchIncidentJobs(expandedId);
    } catch {
      toast.error("Retry failed");
    } finally {
      setActionLoading(null);
    }
  };

  const handleCancel = async (jobId) => {
    if (!confirm("Cancel this notification job?")) return;
    setActionLoading(jobId);
    try {
      await operatorApi.cancelNotificationJob(jobId);
      toast.success("Notification job cancelled");
      if (expandedId) await fetchIncidentJobs(expandedId);
    } catch {
      toast.error("Cancel failed");
    } finally {
      setActionLoading(null);
    }
  };

  const jobStColor = (st) => {
    if (st === 'sent') return 'text-emerald-700 bg-emerald-50';
    if (st === 'dead_letter') return 'text-red-700 bg-red-50';
    if (st === 'retrying') return 'text-orange-700 bg-orange-50';
    if (st === 'cancelled') return 'text-slate-500 bg-slate-100';
    return 'text-yellow-700 bg-yellow-50';
  };

  const chIcon = (ch) => ch === 'email' ? <Mail className="w-3.5 h-3.5" /> : ch === 'sms' ? <MessageSquare className="w-3.5 h-3.5" /> : <Zap className="w-3.5 h-3.5" />;

  if (loading) {
    return <div className="flex items-center justify-center h-64"><Loader2 className="w-8 h-8 animate-spin text-amber-500" /></div>;
  }

  return (
    <div className="space-y-6" data-testid="op-incidents-page">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold text-slate-800">All Incidents ({incidents.length})</h2>
        <div className="flex gap-2">
          <div className="relative">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <Input placeholder="Search..." className="pl-9 w-48" value={search} onChange={(e) => setSearch(e.target.value)} data-testid="op-incidents-search" />
          </div>
          <select className="border rounded-md px-3 py-2 text-sm bg-white" value={filter.status} onChange={(e) => setFilter(f => ({...f, status: e.target.value}))} data-testid="op-filter-status">
            <option value="">All Status</option>
            <option value="open">Open</option>
            <option value="acknowledged">Acknowledged</option>
            <option value="resolved">Resolved</option>
            <option value="false_alarm">False Alarm</option>
          </select>
          <select className="border rounded-md px-3 py-2 text-sm bg-white" value={filter.severity} onChange={(e) => setFilter(f => ({...f, severity: e.target.value}))} data-testid="op-filter-severity">
            <option value="">All Severity</option>
            <option value="critical">Critical</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </select>
          <Button variant="outline" size="sm" onClick={onRefresh}><RefreshCw className="w-4 h-4" /></Button>
        </div>
      </div>

      <Card>
        <CardContent className="pt-6">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Type</TableHead>
                <TableHead>Severity</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Level</TableHead>
                <TableHead>Escalated</TableHead>
                <TableHead>Created</TableHead>
                <TableHead className="w-10"></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((inc) => (
                <React.Fragment key={inc.id}>
                  <TableRow
                    className={`cursor-pointer transition-colors hover:bg-slate-50 ${
                      inc.escalation_level === 3 ? 'bg-red-50 border-l-4 border-l-red-600' :
                      inc.escalation_level === 2 ? 'bg-amber-50 border-l-4 border-l-amber-500' : ''
                    } ${expandedId === inc.id ? 'bg-slate-50' : ''}`}
                    onClick={() => toggleJobs(inc.id)}
                    data-testid={`op-incident-row-${inc.id}`}
                  >
                  <TableCell className="font-medium">
                    {inc.escalation_level === 3 && <AlertTriangle className="w-4 h-4 text-red-600 inline mr-1" />}
                    {inc.is_test && <Badge className="bg-amber-100 text-amber-700 mr-1 text-[10px]">TEST</Badge>}
                    {inc.incident_type.replace(/_/g, ' ')}
                  </TableCell>
                  <TableCell><Badge className={severityColor(inc.severity)}>{inc.severity}</Badge></TableCell>
                  <TableCell><Badge className={statusColor(inc.status)}>{inc.status}</Badge></TableCell>
                  <TableCell>
                    <Badge className={
                      inc.escalation_level === 3 ? 'bg-red-600 text-white' :
                      inc.escalation_level === 2 ? 'bg-amber-500 text-white' :
                      'bg-slate-400 text-white'
                    }>L{inc.escalation_level}</Badge>
                  </TableCell>
                  <TableCell>{inc.escalated ? <CheckCircle className="w-4 h-4 text-amber-500" /> : <XCircle className="w-4 h-4 text-slate-300" />}</TableCell>
                  <TableCell className="text-slate-500 text-sm">{new Date(inc.created_at).toLocaleString()}</TableCell>
                  <TableCell>
                    <Send className={`w-4 h-4 transition-transform ${expandedId === inc.id ? 'text-amber-500 rotate-45' : 'text-slate-300'}`} />
                  </TableCell>
                </TableRow>
                {expandedId === inc.id && (
                  <TableRow>
                    <TableCell colSpan={7} className="bg-slate-50 p-0">
                      <div className="px-6 py-4" data-testid={`op-incident-jobs-${inc.id}`}>
                        {/* Acknowledge button for open incidents */}
                        {inc.status === 'open' && !inc.acknowledged_at && (
                          <div className="flex items-center gap-2 mb-3 p-2 bg-amber-50 rounded-lg border border-amber-200" data-testid={`ack-section-${inc.id}`}>
                            <AlertTriangle className="w-4 h-4 text-amber-500 shrink-0" />
                            <span className="text-sm text-amber-700 flex-1">Unacknowledged — auto-escalation active</span>
                            <Button
                              size="sm"
                              className="h-7 text-xs bg-green-600 hover:bg-green-700"
                              onClick={async (e) => {
                                e.stopPropagation();
                                try {
                                  await operatorApi.acknowledgeIncident(inc.id);
                                  toast.success('Incident acknowledged — escalation stopped');
                                  onRefresh();
                                } catch { toast.error('Failed to acknowledge'); }
                              }}
                              data-testid={`ack-btn-${inc.id}`}
                            >
                              <CheckCircle className="w-3 h-3 mr-1" /> Acknowledge
                            </Button>
                          </div>
                        )}
                        {/* Metric Trends for this incident's device */}
                        {inc.device_id && (
                          <IncidentMetricTrends deviceId={inc.device_id} incidentCreatedAt={inc.created_at} />
                        )}
                        {/* AI Narrative */}
                        <IncidentNarrative incidentId={inc.id} />
                        <h4 className="text-sm font-semibold text-slate-700 mb-3 flex items-center gap-1.5 mt-3">
                          <Send className="w-3.5 h-3.5 text-slate-500" />
                          Notification Delivery for this Incident
                        </h4>
                        {jobsLoading ? (
                          <div className="flex items-center gap-2 text-sm text-slate-400 py-2">
                            <Loader2 className="w-4 h-4 animate-spin" /> Loading jobs...
                          </div>
                        ) : incJobs.length === 0 ? (
                          <p className="text-sm text-slate-400 py-2">No notification jobs for this incident</p>
                        ) : (
                          <div className="grid gap-2">
                            {incJobs.map((job) => (
                              <div key={job.id} className="flex items-center gap-3 text-sm py-2 px-3 rounded-lg bg-white border border-slate-100" data-testid={`op-notif-job-${job.id}`}>
                                <span className="text-slate-400">{chIcon(job.channel)}</span>
                                <span className="uppercase text-xs font-semibold text-slate-500 w-12">{job.channel}</span>
                                <span className="font-mono text-slate-600 truncate max-w-[200px]">{job.recipient}</span>
                                <Badge className={`${jobStColor(job.status)} text-xs`}>{job.status}</Badge>
                                {job.escalation_level && (
                                  <span className="text-xs text-slate-400 font-medium">L{job.escalation_level}</span>
                                )}
                                <span className="text-xs text-slate-400">
                                  {job.attempts > 0 ? `${job.attempts} attempt${job.attempts > 1 ? 's' : ''}` : ''}
                                </span>
                                {job.status === 'dead_letter' && <SkullIcon className="w-3.5 h-3.5 text-red-500" />}
                                <span className="ml-auto text-xs text-slate-400">
                                  {job.created_at ? new Date(job.created_at).toLocaleString() : ''}
                                </span>
                                <div className="flex items-center gap-1.5 shrink-0">
                                  {(job.status === 'dead_letter' || job.status === 'failed') && (
                                    <Button
                                      size="sm"
                                      variant="outline"
                                      className="h-7 px-2 text-xs"
                                      onClick={(e) => { e.stopPropagation(); handleRetry(job.id); }}
                                      disabled={actionLoading === job.id}
                                      data-testid={`op-retry-job-${job.id}`}
                                    >
                                      {actionLoading === job.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <RotateCcw className="w-3 h-3 mr-1" />}
                                      Retry
                                    </Button>
                                  )}
                                  {(job.status === 'pending' || job.status === 'retrying') && (
                                    <Button
                                      size="sm"
                                      variant="destructive"
                                      className="h-7 px-2 text-xs"
                                      onClick={(e) => { e.stopPropagation(); handleCancel(job.id); }}
                                      disabled={actionLoading === job.id}
                                      data-testid={`op-cancel-job-${job.id}`}
                                    >
                                      {actionLoading === job.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <XCircle className="w-3 h-3 mr-1" />}
                                      Cancel
                                    </Button>
                                  )}
                                </div>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                )}
                </React.Fragment>
              ))}
              {filtered.length === 0 && (
                <TableRow><TableCell colSpan={7} className="text-center text-slate-400 py-8">No incidents match filters</TableCell></TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
};

const SettingsPage = () => {
  const [providers, setProviders] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    operatorApi.getNotificationProviders()
      .then(res => setProviders(res.data))
      .catch(() => toast.error('Failed to load provider status'))
      .finally(() => setLoading(false));
  }, []);

  const statusBadge = (live) => (
    <Badge className={live ? 'bg-green-100 text-green-700' : 'bg-slate-100 text-slate-500'} data-testid={`provider-status-${live ? 'live' : 'stub'}`}>
      {live ? 'Live' : 'Stub'}
    </Badge>
  );

  return (
    <div className="space-y-6" data-testid="op-settings-page">
      <h2 className="text-2xl font-bold text-slate-800">Settings</h2>

      <Card>
        <CardContent className="p-6 space-y-4">
          <h3 className="text-lg font-semibold text-slate-800 flex items-center gap-2" data-testid="notification-providers-title">
            <Bell className="w-5 h-5 text-blue-500" />
            Notification Providers
          </h3>
          <p className="text-sm text-slate-500">Status of notification delivery channels. Live channels send real messages; stub channels log only.</p>

          {loading ? (
            <div className="flex items-center justify-center py-8"><Loader2 className="w-5 h-5 animate-spin" /></div>
          ) : providers ? (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3" data-testid="providers-grid">
              {[
                { key: 'sms', icon: <Phone className="w-5 h-5 text-emerald-500" />, label: 'SMS', desc: 'Twilio SMS delivery' },
                { key: 'push', icon: <Bell className="w-5 h-5 text-purple-500" />, label: 'Push', desc: 'Firebase Cloud Messaging' },
                { key: 'email', icon: <Mail className="w-5 h-5 text-blue-500" />, label: 'Email', desc: 'AWS SES email delivery' },
                { key: 'in_app', icon: <Inbox className="w-5 h-5 text-amber-500" />, label: 'In-App', desc: 'Dashboard notifications' },
              ].map(ch => (
                <div key={ch.key} className="flex items-center gap-3 p-4 rounded-lg border border-slate-100 bg-slate-50/50" data-testid={`provider-card-${ch.key}`}>
                  <div className="shrink-0">{ch.icon}</div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-slate-800">{ch.label}</span>
                      {statusBadge(providers[ch.key]?.live)}
                    </div>
                    <p className="text-xs text-slate-400 mt-0.5">{providers[ch.key]?.provider || 'unknown'} — {ch.desc}</p>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-slate-400 text-sm">Unable to load provider status.</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
};

const OperatorConsole = () => {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [stats, setStats] = useState(null);
  const [incidents, setIncidents] = useState([]);
  const [falseMetrics, setFalseMetrics] = useState(null);
  const [deliveryStats, setDeliveryStats] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [statsRes, incRes, falseRes, deliveryRes] = await Promise.all([
        api.get('/operator/stats'),
        api.get('/operator/incidents'),
        api.get('/operator/false-alarm-metrics'),
        api.get('/operator/notification-jobs/stats?window_minutes=15'),
      ]);
      setStats(statsRes.data);
      setIncidents(incRes.data);
      setFalseMetrics(falseRes.data);
      setDeliveryStats(deliveryRes.data);
    } catch (err) {
      if (err.response?.status === 403) {
        toast.error('Access denied. Operator role required.');
        navigate('/login');
      } else {
        toast.error('Failed to load operator data');
      }
    } finally {
      setLoading(false);
    }
  }, [navigate]);

  useEffect(() => { fetchData(); }, [fetchData]);

  // SSE with auto-reconnect
  const [sseStatus, setSseStatus] = useState('disconnected');
  const sseRef = useRef(null);

  useEffect(() => {
    const handleEvent = (eventType, data) => {
      if ([
        'incident_created', 'incident_updated',
        'escalation_l1', 'escalation_l2', 'escalation_l3',
        'notification_job_updated',
        'device_offline_detected', 'device_back_online',
      ].includes(eventType)) {
        fetchData();
      }
    };

    const handleError = () => setSseStatus('reconnecting');
    const handleStatus = (status) => setSseStatus(status);

    sseRef.current = createEventSource(handleEvent, handleError, handleStatus);

    return () => {
      sseRef.current?.close();
      setSseStatus('disconnected');
    };
  }, [fetchData]);

  // 15s silent polling for delivery health
  const pollingRef = useRef(null);
  useEffect(() => {
    pollingRef.current = setInterval(async () => {
      try {
        const { data } = await api.get('/operator/notification-jobs/stats?window_minutes=15');
        setDeliveryStats(data);
      } catch { /* silent */ }
    }, 15000);
    return () => clearInterval(pollingRef.current);
  }, []);

  const handleLogout = () => {
    sseRef.current?.close();
    logout();
    navigate('/login');
  };

  return (
    <div className="flex min-h-screen bg-slate-100" data-testid="operator-console">
      <Sidebar stats={stats} onLogout={handleLogout} sseStatus={sseStatus} user={user} />
      <main className="flex-1 p-8">
        <Routes>
          <Route index element={<Dashboard stats={stats} falseMetrics={falseMetrics} deliveryStats={deliveryStats} incidents={incidents} loading={loading} onRefresh={fetchData} />} />
          <Route path="command-center" element={<CommandCenter />} />
          <Route path="incidents" element={<IncidentsPage incidents={incidents} loading={loading} onRefresh={fetchData} />} />
          <Route path="device-health" element={<DeviceHealthPage />} />
          <Route path="location-risk" element={<LocationRiskHeatmap />} />
          <Route path="route-safety" element={<RouteSafetyIntelligence />} />
          <Route path="incident-replay/:incidentId" element={<IncidentReplayPage />} />
          <Route path="health-rules" element={<HealthRulesPage />} />
          <Route path="simulation" element={<SimulationLab />} />
          <Route path="escalation-analytics" element={<EscalationAnalytics />} />
          <Route path="escalation" element={<EscalationDashboard />} />
          <Route path="risk-learning" element={<RiskLearningDashboard />} />
          <Route path="activity-risk" element={<HumanActivityRiskPage />} />
          <Route path="patrol-ai" element={<PatrolAIDashboard />} />
          <Route path="city-heatmap" element={<CityHeatmapDashboard />} />
          <Route path="safe-zones" element={<SafeZoneDashboard />} />
          <Route path="night-guardian" element={<NightGuardianDashboard />} />
          <Route path="safe-route" element={<SafeRouteDashboard />} />
          <Route path="guardian-mode" element={<GuardianModeDashboard />} />
          <Route path="predictive-alerts" element={<PredictiveAlertDashboard />} />
          <Route path="safety-score" element={<SafetyScoreDashboard />} />
          <Route path="settings" element={<SettingsPage />} />
        </Routes>
      </main>
    </div>
  );
};

// ── Incident Replay Page (standalone access) ──
function IncidentReplayPage() {
  const { incidentId } = useParams();
  const navigate = useNavigate();
  return <IncidentReplayViewer incidentId={incidentId} onClose={() => navigate('/operator/incidents')} />;
}

export default OperatorConsole;
