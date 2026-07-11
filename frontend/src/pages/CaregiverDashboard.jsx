import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import api from '../api';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import {
  Heart, AlertTriangle, Loader2, Shield, Clock, CheckCircle, User as UserIcon,
  RefreshCw, Clipboard, Activity, FileText, Plus, X, Power,
} from 'lucide-react';
import { toast } from 'sonner';

const SEV = { critical: 'bg-red-500/15 text-red-400 border-red-500/30', high: 'bg-orange-500/15 text-orange-400 border-orange-500/30', medium: 'bg-amber-500/15 text-amber-400 border-amber-500/30', low: 'bg-slate-500/15 text-slate-400 border-slate-500/30' };
const STATUS_OPTS = ['available', 'busy', 'offline'];

/* Header */
const CaregiverHeader = ({ profile, alerts, visits, onStatusChange, onRefresh, refreshing }) => (
  <div className="bg-slate-900 border-b border-slate-700/50 px-6 flex items-center justify-between" data-testid="caregiver-header">
    <div className="flex items-center gap-3">
      <div className="w-9 h-9 rounded-lg bg-emerald-500/20 flex items-center justify-center border border-emerald-500/30">
        <Heart className="w-5 h-5 text-emerald-400" />
      </div>
      <div>
        <h1 className="text-base font-bold text-white">Caregiver Dashboard</h1>
        <span className="text-[10px] text-slate-400">{profile?.full_name || profile?.email || 'Loading...'}</span>
      </div>
    </div>
    <div className="flex items-center gap-3">
      <div className="px-3 py-1.5 rounded-lg bg-red-500/10 border border-red-500/20" data-testid="cg-active-alerts">
        <p className="text-[9px] text-slate-500 uppercase">Alerts</p>
        <p className="text-lg font-bold text-red-400 leading-tight">{alerts}</p>
      </div>
      <div className="px-3 py-1.5 rounded-lg bg-emerald-500/10 border border-emerald-500/20" data-testid="cg-visits">
        <p className="text-[9px] text-slate-500 uppercase">Visits Today</p>
        <p className="text-lg font-bold text-emerald-400 leading-tight">{visits}</p>
      </div>
      <select className="h-8 rounded border border-slate-600 bg-slate-800 text-xs text-slate-300 px-2" value={profile?.status || 'available'} onChange={e => onStatusChange(e.target.value)} data-testid="cg-status-select">
        {STATUS_OPTS.map(s => <option key={s} value={s}>{s}</option>)}
      </select>
      <Button size="sm" variant="ghost" className="text-slate-400" onClick={onRefresh}>
        <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin' : ''}`} />
      </Button>
    </div>
  </div>
);

/* Assigned Users List */
const AssignedUsersList = ({ users, selectedId, onSelect, filter, setFilter }) => (
  <div className="bg-slate-800/40 rounded-lg border border-slate-700/50 flex flex-col h-full" data-testid="assigned-users-list">
    <div className="px-3 py-2 border-b border-slate-700/50 flex items-center justify-between shrink-0">
      <h3 className="text-sm font-semibold text-white flex items-center gap-1.5"><UserIcon className="w-3.5 h-3.5 text-blue-400" />Assigned</h3>
      <span className="text-[10px] bg-slate-700/50 text-slate-400 px-2 py-0.5 rounded-full">{users.length}</span>
    </div>
    <div className="flex gap-1 px-2 pt-2">
      {['all', 'high', 'alert', 'not_visited'].map(f => (
        <button key={f} onClick={() => setFilter(f)} className={`text-[9px] px-2 py-1 rounded ${filter === f ? 'bg-teal-500/20 text-teal-400' : 'text-slate-500 hover:text-slate-300'}`}>{f.replace('_',' ')}</button>
      ))}
    </div>
    <div className="flex-1 overflow-y-auto p-2 space-y-1.5">
      {users.length === 0 ? <p className="text-xs text-slate-500 text-center py-6">No assigned users</p> : users.map(u => (
        <button key={u.id} onClick={() => onSelect(u)} className={`w-full text-left p-2.5 rounded-lg border transition-all ${selectedId === u.id ? 'border-teal-500/50 bg-teal-500/10' : 'border-slate-700/30 bg-slate-800/30 hover:border-slate-600'}`} data-testid={`assigned-user-${u.id}`}>
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs font-medium text-slate-300 truncate">{u.full_name}</span>
            <Badge className={`text-[8px] px-1 py-0 border ${u.risk_status === 'high' ? SEV.high : SEV.low}`}>{u.risk_status}</Badge>
          </div>
          <div className="flex items-center gap-2 text-[9px] text-slate-500">
            {u.age && <span>Age: {u.age}</span>}
            {u.active_incidents > 0 && <span className="text-red-400">{u.active_incidents} alerts</span>}
            {u.last_visit && <span>Visit: {new Date(u.last_visit).toLocaleDateString()}</span>}
          </div>
        </button>
      ))}
    </div>
  </div>
);

/* Alert Panel */
const CaregiverAlertPanel = ({ alerts, onAcknowledge, onUpdateStatus }) => (
  <div className="bg-slate-800/40 rounded-lg border border-slate-700/50 flex flex-col h-full" data-testid="caregiver-alert-panel">
    <div className="px-3 py-2 border-b border-slate-700/50 flex items-center gap-1.5 shrink-0">
      <AlertTriangle className="w-3.5 h-3.5 text-red-400" />
      <h3 className="text-sm font-semibold text-white">Active Alerts</h3>
    </div>
    <div className="flex-1 overflow-y-auto p-2 space-y-2">
      {alerts.length === 0 ? <p className="text-xs text-slate-500 text-center py-6">No active alerts</p> : alerts.map(a => (
        <div key={a.id} className={`p-3 rounded-lg border ${SEV[a.severity] || SEV.low}`} data-testid={`cg-alert-${a.id}`}>
          <div className="flex items-center justify-between mb-1">
            <Badge className={`text-[9px] border ${SEV[a.severity] || SEV.low}`}>{a.severity}</Badge>
            <span className="text-[9px] text-slate-500">{a.created_at ? new Date(a.created_at).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}) : ''}</span>
          </div>
          <p className="text-xs text-slate-300">{a.incident_type?.replace('_',' ')} — {a.senior_name}</p>
          <Badge className={`text-[8px] mt-1 ${a.status === 'open' ? 'bg-red-500/20 text-red-400' : 'bg-blue-500/20 text-blue-400'}`}>{a.status}</Badge>
          <div className="flex gap-1.5 mt-2">
            {!a.acknowledged_at && <Button size="sm" className="h-6 text-[9px]" onClick={() => onAcknowledge(a.id)} data-testid={`ack-${a.id}`}><CheckCircle className="w-2.5 h-2.5 mr-1" />Ack</Button>}
            <Button size="sm" variant="outline" className="h-6 text-[9px] border-blue-500/30 text-blue-400" onClick={() => onUpdateStatus(a.id, 'in_progress')}><Activity className="w-2.5 h-2.5 mr-1" />Start</Button>
            <Button size="sm" variant="outline" className="h-6 text-[9px] border-emerald-500/30 text-emerald-400" onClick={() => onUpdateStatus(a.id, 'resolved')}><CheckCircle className="w-2.5 h-2.5 mr-1" />Resolve</Button>
          </div>
        </div>
      ))}
    </div>
  </div>
);

/* Visit Log */
const VisitLogPanel = ({ visits, users, onCreateVisit }) => {
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ senior_id: '', purpose: '', remarks: '' });
  const [saving, setSaving] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      await onCreateVisit(form);
      setForm({ senior_id: '', purpose: '', remarks: '' });
      setShowForm(false);
    } catch {}
    setSaving(false);
  };

  return (
    <div className="bg-slate-800/40 rounded-lg border border-slate-700/50 flex flex-col h-full" data-testid="visit-log-panel">
      <div className="px-3 py-2 border-b border-slate-700/50 flex items-center justify-between shrink-0">
        <h3 className="text-sm font-semibold text-white flex items-center gap-1.5"><Clipboard className="w-3.5 h-3.5 text-teal-400" />Visit Log</h3>
        <Button size="sm" variant="ghost" className="h-6 text-[10px] text-teal-400" onClick={() => setShowForm(!showForm)} data-testid="new-visit-btn">
          {showForm ? <X className="w-3 h-3" /> : <Plus className="w-3 h-3 mr-1" />}{showForm ? '' : 'New Visit'}
        </Button>
      </div>
      {showForm && (
        <form onSubmit={handleSubmit} className="p-2 space-y-1.5 border-b border-slate-700/30">
          <select className="w-full h-7 rounded border border-slate-600 bg-slate-800 text-[10px] text-slate-300 px-2" value={form.senior_id} onChange={e => setForm(f => ({...f, senior_id: e.target.value}))} required data-testid="visit-senior-select">
            <option value="">Select patient...</option>
            {users.map(u => <option key={u.id} value={u.id}>{u.full_name}</option>)}
          </select>
          <Input className="h-7 text-[10px] bg-slate-800 border-slate-600 text-slate-300" placeholder="Purpose" value={form.purpose} onChange={e => setForm(f => ({...f, purpose: e.target.value}))} required data-testid="visit-purpose" />
          <Input className="h-7 text-[10px] bg-slate-800 border-slate-600 text-slate-300" placeholder="Remarks (optional)" value={form.remarks} onChange={e => setForm(f => ({...f, remarks: e.target.value}))} />
          <Button size="sm" type="submit" className="h-6 text-[10px] w-full" disabled={saving} data-testid="visit-submit">{saving ? <Loader2 className="w-3 h-3 animate-spin" /> : 'Log Visit'}</Button>
        </form>
      )}
      <div className="flex-1 overflow-y-auto p-2 space-y-1">
        {visits.length === 0 ? <p className="text-xs text-slate-500 text-center py-3">No visits logged today</p> : visits.map(v => (
          <div key={v.id} className="flex items-center gap-2 p-2 rounded bg-slate-700/20 border border-slate-700/40">
            <Clock className="w-3 h-3 text-slate-500 shrink-0" />
            <div className="min-w-0">
              <p className="text-[10px] text-slate-300 truncate">{v.purpose} — {v.senior_name}</p>
              <p className="text-[8px] text-slate-500">{new Date(v.visited_at).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'})}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

/* Health Notes */
const HealthNotesPanel = ({ notes, users, onCreateNote }) => {
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ senior_id: '', observation_type: '', severity: 'low', notes: '', follow_up: '' });
  const [saving, setSaving] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      await onCreateNote(form);
      setForm({ senior_id: '', observation_type: '', severity: 'low', notes: '', follow_up: '' });
      setShowForm(false);
    } catch {}
    setSaving(false);
  };

  return (
    <div className="bg-slate-800/40 rounded-lg border border-slate-700/50 flex flex-col h-full" data-testid="health-notes-panel">
      <div className="px-3 py-2 border-b border-slate-700/50 flex items-center justify-between shrink-0">
        <h3 className="text-sm font-semibold text-white flex items-center gap-1.5"><FileText className="w-3.5 h-3.5 text-violet-400" />Health Notes</h3>
        <Button size="sm" variant="ghost" className="h-6 text-[10px] text-violet-400" onClick={() => setShowForm(!showForm)} data-testid="new-note-btn">
          {showForm ? <X className="w-3 h-3" /> : <Plus className="w-3 h-3 mr-1" />}{showForm ? '' : 'New Note'}
        </Button>
      </div>
      {showForm && (
        <form onSubmit={handleSubmit} className="p-2 space-y-1.5 border-b border-slate-700/30">
          <select className="w-full h-7 rounded border border-slate-600 bg-slate-800 text-[10px] text-slate-300 px-2" value={form.senior_id} onChange={e => setForm(f => ({...f, senior_id: e.target.value}))} required data-testid="note-senior-select">
            <option value="">Select patient...</option>
            {users.map(u => <option key={u.id} value={u.id}>{u.full_name}</option>)}
          </select>
          <Input className="h-7 text-[10px] bg-slate-800 border-slate-600 text-slate-300" placeholder="Observation type" value={form.observation_type} onChange={e => setForm(f => ({...f, observation_type: e.target.value}))} required data-testid="note-type" />
          <select className="w-full h-7 rounded border border-slate-600 bg-slate-800 text-[10px] text-slate-300 px-2" value={form.severity} onChange={e => setForm(f => ({...f, severity: e.target.value}))} data-testid="note-severity">
            {['low','medium','high','critical'].map(s => <option key={s} value={s}>{s}</option>)}
          </select>
          <textarea className="w-full rounded border border-slate-600 bg-slate-800 text-[10px] text-slate-300 p-2 h-14" placeholder="Notes..." value={form.notes} onChange={e => setForm(f => ({...f, notes: e.target.value}))} required data-testid="note-text" />
          <Input className="h-7 text-[10px] bg-slate-800 border-slate-600 text-slate-300" placeholder="Follow-up (optional)" value={form.follow_up} onChange={e => setForm(f => ({...f, follow_up: e.target.value}))} />
          <Button size="sm" type="submit" className="h-6 text-[10px] w-full" disabled={saving} data-testid="note-submit">{saving ? <Loader2 className="w-3 h-3 animate-spin" /> : 'Save Note'}</Button>
        </form>
      )}
      <div className="flex-1 overflow-y-auto p-2 space-y-1">
        {notes.length === 0 ? <p className="text-xs text-slate-500 text-center py-3">No notes yet</p> : notes.map(n => (
          <div key={n.id} className={`p-2 rounded border ${SEV[n.severity] || SEV.low}`}>
            <div className="flex items-center justify-between">
              <span className="text-[10px] font-medium text-slate-300">{n.observation_type}</span>
              <Badge className={`text-[8px] border ${SEV[n.severity] || SEV.low}`}>{n.severity}</Badge>
            </div>
            <p className="text-[9px] text-slate-400 mt-0.5 truncate">{n.notes}</p>
            <p className="text-[8px] text-slate-500">{n.senior_name} — {new Date(n.created_at).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'})}</p>
          </div>
        ))}
      </div>
    </div>
  );
};

/* ═══════════════════════════════════════════════════════════════
   MAIN CAREGIVER DASHBOARD
   ═══════════════════════════════════════════════════════════════ */
export default function CaregiverDashboard() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [profile, setProfile] = useState(null);
  const [assignedUsers, setAssignedUsers] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [visits, setVisits] = useState([]);
  const [notes, setNotes] = useState([]);
  const [selectedUser, setSelectedUser] = useState(null);
  const [userFilter, setUserFilter] = useState('all');
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const isAuthorized = user?.role === 'admin' || user?.role === 'caregiver' || user?.roles?.includes('admin') || user?.roles?.includes('caregiver');

  const fetchData = useCallback(async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true);
    try {
      const [pRes, uRes, aRes, vRes, nRes] = await Promise.all([
        api.get('/caregiver/profile').catch(() => null),
        api.get('/caregiver/assigned-users').catch(() => null),
        api.get('/caregiver/alerts').catch(() => null),
        api.get('/caregiver/visits?limit=20').catch(() => null),
        api.get('/caregiver/notes?limit=20').catch(() => null),
      ]);
      if (pRes?.data) setProfile(pRes.data);
      if (uRes?.data) setAssignedUsers(uRes.data.users || []);
      if (aRes?.data) setAlerts(aRes.data.alerts || []);
      if (vRes?.data) setVisits(vRes.data.visits || []);
      if (nRes?.data) setNotes(nRes.data.notes || []);
    } catch {}
    setLoading(false);
    setRefreshing(false);
  }, []);

  useEffect(() => {
    if (!isAuthorized) { navigate('/family'); return; }
    fetchData();
  }, [isAuthorized, navigate, fetchData]);

  useEffect(() => { const iv = setInterval(() => fetchData(true), 20000); return () => clearInterval(iv); }, [fetchData]);

  const filteredUsers = assignedUsers.filter(u => {
    if (userFilter === 'all') return true;
    if (userFilter === 'high') return u.risk_status === 'high';
    if (userFilter === 'alert') return u.active_incidents > 0;
    if (userFilter === 'not_visited') return !u.last_visit;
    return true;
  });

  const handleStatusChange = async (newStatus) => {
    try {
      await api.patch('/caregiver/status', { status: newStatus });
      setProfile(p => ({ ...p, status: newStatus }));
      toast.success(`Status: ${newStatus}`);
    } catch { toast.error('Failed to update status'); }
  };

  const handleAcknowledge = async (id) => {
    try { await api.patch(`/caregiver/alerts/${id}/acknowledge`); toast.success('Acknowledged'); fetchData(true); } catch { toast.error('Failed'); }
  };
  const handleAlertStatus = async (id, status) => {
    try { await api.patch(`/caregiver/alerts/${id}/status`, { status }); toast.success(`Status: ${status}`); fetchData(true); } catch { toast.error('Failed'); }
  };
  const handleCreateVisit = async (data) => {
    await api.post('/caregiver/visits', data);
    toast.success('Visit logged');
    fetchData(true);
  };
  const handleCreateNote = async (data) => {
    await api.post('/caregiver/notes', data);
    toast.success('Note saved');
    fetchData(true);
  };

  if (!isAuthorized) return null;
  if (loading) return (
    <div className="h-screen bg-slate-900 flex items-center justify-center">
      <Loader2 className="w-8 h-8 animate-spin text-emerald-500" />
    </div>
  );

  return (
    <div className="h-screen bg-slate-900 text-white grid grid-rows-[68px_1fr_220px] overflow-hidden" data-testid="caregiver-dashboard">
      <CaregiverHeader profile={profile} alerts={alerts.length} visits={visits.length} onStatusChange={handleStatusChange} onRefresh={() => fetchData(true)} refreshing={refreshing} />

      <div className="grid grid-cols-[380px_1fr] gap-3 p-3 min-h-0">
        <AssignedUsersList users={filteredUsers} selectedId={selectedUser?.id} onSelect={setSelectedUser} filter={userFilter} setFilter={setUserFilter} />
        <CaregiverAlertPanel alerts={alerts} onAcknowledge={handleAcknowledge} onUpdateStatus={handleAlertStatus} />
      </div>

      <div className="grid grid-cols-2 gap-3 px-3 pb-3 min-h-0">
        <VisitLogPanel visits={visits} users={assignedUsers} onCreateVisit={handleCreateVisit} />
        <HealthNotesPanel notes={notes} users={assignedUsers} onCreateNote={handleCreateNote} />
      </div>
    </div>
  );
}
