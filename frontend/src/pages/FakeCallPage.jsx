import React, { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import {
  Phone, PhoneCall, PhoneOff, Clock, Plus, Trash2,
  User, Briefcase, Heart, UserCheck, Timer, Shield,
  History, Settings, Loader2, ChevronDown, ChevronUp,
  Volume2, PhoneIncoming, AlertCircle,
} from 'lucide-react';
import api from '../api';
import { toast } from 'sonner';

const LABEL_ICONS = {
  Family: Heart,
  Work: Briefcase,
  Friend: User,
  Medical: Plus,
  Custom: UserCheck,
};

const LABEL_COLORS = {
  Family: { bg: 'bg-rose-50', border: 'border-rose-200', text: 'text-rose-700', accent: '#e11d48' },
  Work: { bg: 'bg-blue-50', border: 'border-blue-200', text: 'text-blue-700', accent: '#2563eb' },
  Friend: { bg: 'bg-emerald-50', border: 'border-emerald-200', text: 'text-emerald-700', accent: '#059669' },
  Medical: { bg: 'bg-amber-50', border: 'border-amber-200', text: 'text-amber-700', accent: '#d97706' },
  Custom: { bg: 'bg-slate-50', border: 'border-slate-200', text: 'text-slate-700', accent: '#475569' },
};

const DELAY_OPTIONS = [
  { label: 'Now', value: 0 },
  { label: '10s', value: 10 },
  { label: '30s', value: 30 },
  { label: '1 min', value: 60 },
  { label: '2 min', value: 120 },
];

const RINGTONE_OPTIONS = ['default', 'classic', 'professional', 'upbeat', 'urgent'];

const PresetCard = ({ preset, onTrigger, onEdit, onDelete, triggerLoading }) => {
  const [delay, setDelay] = useState(0);
  const style = LABEL_COLORS[preset.caller_label] || LABEL_COLORS.Custom;
  const Icon = LABEL_ICONS[preset.caller_label] || UserCheck;

  return (
    <div className={`rounded-xl border-2 ${style.border} ${style.bg} p-4 transition-all hover:shadow-md`} data-testid={`preset-card-${preset.id}`}>
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-3">
          <div className="w-12 h-12 rounded-full flex items-center justify-center text-white text-lg font-bold" style={{ background: style.accent }}>
            {preset.caller_name[0].toUpperCase()}
          </div>
          <div>
            <div className="font-bold text-slate-800" data-testid={`preset-name-${preset.id}`}>{preset.caller_name}</div>
            <div className="flex items-center gap-1.5 mt-0.5">
              <Icon className="w-3 h-3" style={{ color: style.accent }} />
              <span className={`text-xs font-medium ${style.text}`}>{preset.caller_label}</span>
              {preset.is_default && <Badge variant="outline" className="text-[9px] ml-1">Default</Badge>}
            </div>
          </div>
        </div>
        {!preset.is_default && (
          <button onClick={() => onDelete(preset.id)} className="text-slate-400 hover:text-red-500 transition-colors p-1" data-testid={`delete-preset-${preset.id}`}>
            <Trash2 className="w-4 h-4" />
          </button>
        )}
      </div>

      <div className="flex items-center gap-1.5 mb-3">
        <Timer className="w-3 h-3 text-slate-400" />
        <span className="text-[10px] text-slate-500 uppercase tracking-wider font-semibold">Delay:</span>
        {DELAY_OPTIONS.map(d => (
          <button
            key={d.value}
            onClick={() => setDelay(d.value)}
            className={`text-[10px] px-2 py-0.5 rounded-full font-medium transition-all ${
              delay === d.value
                ? 'text-white shadow-sm'
                : 'bg-white/60 text-slate-500 hover:bg-white'
            }`}
            style={delay === d.value ? { background: style.accent } : {}}
            data-testid={`delay-${d.value}-${preset.id}`}
          >
            {d.label}
          </button>
        ))}
      </div>

      <Button
        onClick={() => onTrigger(preset, delay)}
        disabled={triggerLoading}
        className="w-full text-white font-bold text-sm"
        style={{ background: style.accent }}
        data-testid={`trigger-btn-${preset.id}`}
      >
        {triggerLoading ? <Loader2 className="w-4 h-4 mr-1 animate-spin" /> : <PhoneCall className="w-4 h-4 mr-1" />}
        {delay > 0 ? `Call in ${delay}s` : 'Call Now'}
      </Button>

      <div className="flex items-center gap-2 mt-2 text-[10px] text-slate-400">
        <Volume2 className="w-3 h-3" />
        <span>Ringtone: {preset.ringtone_style}</span>
      </div>
    </div>
  );
};

const FakeCallPage = ({ onIncomingCall }) => {
  const [presets, setPresets] = useState([]);
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [triggerLoading, setTriggerLoading] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [newPreset, setNewPreset] = useState({ caller_name: '', caller_label: 'Custom', ringtone_style: 'default' });

  const fetchData = useCallback(async () => {
    try {
      const [presetsRes, historyRes] = await Promise.all([
        api.get('/fake-call/presets'),
        api.get('/fake-call/history?limit=10'),
      ]);
      setPresets(presetsRes.data?.presets || []);
      setHistory(historyRes.data?.history || []);
    } catch {
      toast.error('Failed to load fake call data');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handleTrigger = async (preset, delay) => {
    setTriggerLoading(true);
    try {
      const res = await api.post('/fake-call/trigger', {
        preset_id: preset.id,
        caller_name: preset.caller_name,
        delay_seconds: delay,
        trigger_method: 'dashboard',
      });
      const callData = res.data;

      if (delay > 0) {
        toast.success(`Fake call scheduled in ${delay}s`, { description: `From: ${preset.caller_name}`, duration: delay * 1000 });
        setTimeout(() => {
          onIncomingCall?.({
            call_id: callData.call_id,
            caller_name: preset.caller_name,
            caller_label: preset.caller_label,
            ringtone_style: preset.ringtone_style,
          });
        }, delay * 1000);
      } else {
        onIncomingCall?.({
          call_id: callData.call_id,
          caller_name: preset.caller_name,
          caller_label: preset.caller_label,
          ringtone_style: preset.ringtone_style,
        });
      }
    } catch {
      toast.error('Failed to trigger fake call');
    } finally {
      setTriggerLoading(false);
    }
  };

  const handleCreatePreset = async () => {
    if (!newPreset.caller_name.trim()) return;
    try {
      await api.post('/fake-call/presets', newPreset);
      setNewPreset({ caller_name: '', caller_label: 'Custom', ringtone_style: 'default' });
      setShowCreate(false);
      fetchData();
      toast.success('Preset created');
    } catch {
      toast.error('Failed to create preset');
    }
  };

  const handleDeletePreset = async (id) => {
    try {
      await api.delete(`/fake-call/presets/${id}`);
      fetchData();
      toast.success('Preset deleted');
    } catch {
      toast.error('Cannot delete default preset');
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64" data-testid="fake-call-loading">
        <Loader2 className="w-8 h-8 animate-spin text-teal-600" />
      </div>
    );
  }

  return (
    <div className="space-y-6" data-testid="fake-call-page">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-black text-slate-800 flex items-center gap-2">
            <Phone className="w-6 h-6 text-teal-600" />
            Escape Call
          </h1>
          <p className="text-sm text-slate-500 mt-1">Trigger a simulated incoming call to exit risky situations</p>
        </div>
        <Button variant="outline" size="sm" onClick={() => setShowCreate(!showCreate)} className="text-xs" data-testid="add-preset-btn">
          <Plus className="w-3.5 h-3.5 mr-1" /> New Contact
        </Button>
      </div>

      {/* Quick Alert Banner */}
      <div className="p-3 bg-teal-50 border border-teal-200 rounded-lg flex items-start gap-2" data-testid="escape-info-banner">
        <Shield className="w-4 h-4 text-teal-600 mt-0.5 flex-shrink-0" />
        <div className="text-xs text-teal-700">
          <span className="font-bold">How it works:</span> Tap a contact to trigger a realistic incoming call screen.
          Accept the call to start a simulated conversation. After ending, optionally alert your trusted contacts with your location.
        </div>
      </div>

      {/* Create New Preset */}
      {showCreate && (
        <Card className="border-dashed border-2 border-teal-300" data-testid="create-preset-form">
          <CardContent className="p-4">
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <div>
                <label className="text-[10px] text-slate-500 font-semibold uppercase">Caller Name</label>
                <input
                  value={newPreset.caller_name}
                  onChange={e => setNewPreset(p => ({ ...p, caller_name: e.target.value }))}
                  placeholder="e.g. Doctor Smith"
                  className="mt-1 w-full px-3 py-2 text-sm border rounded-lg focus:outline-none focus:ring-2 focus:ring-teal-400"
                  data-testid="new-preset-name"
                />
              </div>
              <div>
                <label className="text-[10px] text-slate-500 font-semibold uppercase">Category</label>
                <select
                  value={newPreset.caller_label}
                  onChange={e => setNewPreset(p => ({ ...p, caller_label: e.target.value }))}
                  className="mt-1 w-full px-3 py-2 text-sm border rounded-lg focus:outline-none focus:ring-2 focus:ring-teal-400"
                  data-testid="new-preset-label"
                >
                  {Object.keys(LABEL_COLORS).map(l => <option key={l} value={l}>{l}</option>)}
                </select>
              </div>
              <div>
                <label className="text-[10px] text-slate-500 font-semibold uppercase">Ringtone</label>
                <select
                  value={newPreset.ringtone_style}
                  onChange={e => setNewPreset(p => ({ ...p, ringtone_style: e.target.value }))}
                  className="mt-1 w-full px-3 py-2 text-sm border rounded-lg focus:outline-none focus:ring-2 focus:ring-teal-400"
                  data-testid="new-preset-ringtone"
                >
                  {RINGTONE_OPTIONS.map(r => <option key={r} value={r}>{r}</option>)}
                </select>
              </div>
            </div>
            <div className="flex gap-2 mt-3 justify-end">
              <Button variant="outline" size="sm" onClick={() => setShowCreate(false)} data-testid="cancel-preset-btn">Cancel</Button>
              <Button size="sm" onClick={handleCreatePreset} className="bg-teal-600 hover:bg-teal-700 text-white" data-testid="save-preset-btn">Save Contact</Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Preset Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4" data-testid="presets-grid">
        {presets.map(p => (
          <PresetCard
            key={p.id}
            preset={p}
            onTrigger={handleTrigger}
            onDelete={handleDeletePreset}
            triggerLoading={triggerLoading}
          />
        ))}
      </div>

      {/* Call History */}
      <Card data-testid="call-history-card">
        <CardHeader className="pb-2 cursor-pointer" onClick={() => setShowHistory(!showHistory)}>
          <CardTitle className="text-sm font-bold text-slate-700 flex items-center gap-2">
            <History className="w-4 h-4" /> Call History ({history.length})
            {showHistory ? <ChevronUp className="w-4 h-4 ml-auto" /> : <ChevronDown className="w-4 h-4 ml-auto" />}
          </CardTitle>
        </CardHeader>
        {showHistory && (
          <CardContent>
            {history.length === 0 ? (
              <p className="text-xs text-slate-400 text-center py-4">No calls yet</p>
            ) : (
              <div className="space-y-2">
                {history.map(h => (
                  <div key={h.id} className="flex items-center gap-3 p-2 rounded-lg bg-slate-50 border" data-testid={`history-${h.id}`}>
                    <div className={`w-8 h-8 rounded-full flex items-center justify-center ${h.answered ? 'bg-green-100' : 'bg-red-100'}`}>
                      {h.answered ? <PhoneCall className="w-4 h-4 text-green-600" /> : <PhoneOff className="w-4 h-4 text-red-500" />}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="text-xs font-bold text-slate-700">{h.caller_name}</div>
                      <div className="text-[10px] text-slate-400">
                        {new Date(h.triggered_at).toLocaleString()} | {h.trigger_method}
                        {h.duration_seconds > 0 && ` | ${h.duration_seconds}s`}
                      </div>
                    </div>
                    <div className="flex items-center gap-1">
                      {h.alert_sent && <Badge className="bg-amber-100 text-amber-700 text-[9px]">Alert Sent</Badge>}
                      <Badge className={`text-[9px] ${h.status === 'completed' ? 'bg-green-100 text-green-700' : 'bg-slate-100 text-slate-600'}`}>
                        {h.status}
                      </Badge>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        )}
      </Card>
    </div>
  );
};

export default FakeCallPage;
