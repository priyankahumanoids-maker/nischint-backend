import React, { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import {
  BellRing, Plus, Trash2, Timer, Shield, History, Loader2,
  ChevronDown, ChevronUp, Calendar, Package, ShieldAlert,
  MessageCircle, FileText, Clock, Eye, X, Send,
} from 'lucide-react';
import api from '../api';
import { toast } from 'sonner';

const CATEGORY_META = {
  Work: { icon: Calendar, accent: '#2563eb', bg: 'bg-blue-50', border: 'border-blue-200', text: 'text-blue-700' },
  Delivery: { icon: Package, accent: '#059669', bg: 'bg-emerald-50', border: 'border-emerald-200', text: 'text-emerald-700' },
  Security: { icon: ShieldAlert, accent: '#dc2626', bg: 'bg-red-50', border: 'border-red-200', text: 'text-red-700' },
  Message: { icon: MessageCircle, accent: '#7c3aed', bg: 'bg-violet-50', border: 'border-violet-200', text: 'text-violet-700' },
  Custom: { icon: FileText, accent: '#475569', bg: 'bg-slate-50', border: 'border-slate-200', text: 'text-slate-700' },
};

const DELAY_OPTIONS = [
  { label: 'Now', value: 0 },
  { label: '10s', value: 10 },
  { label: '30s', value: 30 },
  { label: '1 min', value: 60 },
  { label: '2 min', value: 120 },
];

const ICON_OPTIONS = ['default', 'calendar', 'package', 'shield', 'message', 'alert'];

const PresetCard = ({ preset, onTrigger, onDelete, triggerLoading }) => {
  const [delay, setDelay] = useState(0);
  const meta = CATEGORY_META[preset.category] || CATEGORY_META.Custom;
  const Icon = meta.icon;

  return (
    <div className={`rounded-xl border-2 ${meta.border} ${meta.bg} p-4 transition-all hover:shadow-md`} data-testid={`notif-preset-${preset.id}`}>
      <div className="flex items-start justify-between mb-2">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg flex items-center justify-center text-white" style={{ background: meta.accent }}>
            <Icon className="w-5 h-5" />
          </div>
          <div className="min-w-0">
            <div className="font-bold text-slate-800 text-sm truncate" data-testid={`notif-preset-title-${preset.id}`}>{preset.title}</div>
            <div className="flex items-center gap-1.5 mt-0.5">
              <span className={`text-[10px] font-semibold ${meta.text}`}>{preset.category}</span>
              {preset.is_default && <Badge variant="outline" className="text-[9px]">Default</Badge>}
            </div>
          </div>
        </div>
        {!preset.is_default && (
          <button onClick={() => onDelete(preset.id)} className="text-slate-400 hover:text-red-500 transition-colors p-1" data-testid={`delete-notif-preset-${preset.id}`}>
            <Trash2 className="w-4 h-4" />
          </button>
        )}
      </div>

      <p className="text-xs text-slate-500 mb-3 line-clamp-2">{preset.message}</p>

      <div className="flex items-center gap-1.5 mb-3">
        <Timer className="w-3 h-3 text-slate-400" />
        <span className="text-[10px] text-slate-500 uppercase tracking-wider font-semibold">Delay:</span>
        {DELAY_OPTIONS.map(d => (
          <button
            key={d.value}
            onClick={() => setDelay(d.value)}
            className={`text-[10px] px-2 py-0.5 rounded-full font-medium transition-all ${
              delay === d.value ? 'text-white shadow-sm' : 'bg-white/60 text-slate-500 hover:bg-white'
            }`}
            style={delay === d.value ? { background: meta.accent } : {}}
            data-testid={`notif-delay-${d.value}-${preset.id}`}
          >
            {d.label}
          </button>
        ))}
      </div>

      <Button
        onClick={() => onTrigger(preset, delay)}
        disabled={triggerLoading}
        className="w-full text-white font-bold text-sm"
        style={{ background: meta.accent }}
        data-testid={`notif-trigger-btn-${preset.id}`}
      >
        {triggerLoading ? <Loader2 className="w-4 h-4 mr-1 animate-spin" /> : <Send className="w-4 h-4 mr-1" />}
        {delay > 0 ? `Send in ${delay}s` : 'Send Now'}
      </Button>
    </div>
  );
};

const FakeNotificationPage = ({ onNotification }) => {
  const [presets, setPresets] = useState([]);
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [triggerLoading, setTriggerLoading] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [newPreset, setNewPreset] = useState({ title: '', message: '', category: 'Custom', icon_style: 'default' });

  const fetchData = useCallback(async () => {
    try {
      const [presetsRes, historyRes] = await Promise.all([
        api.get('/fake-notification/presets'),
        api.get('/fake-notification/history?limit=10'),
      ]);
      setPresets(presetsRes.data?.presets || []);
      setHistory(historyRes.data?.history || []);
    } catch {
      toast.error('Failed to load notification data');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handleTrigger = async (preset, delay) => {
    setTriggerLoading(true);
    try {
      const res = await api.post('/fake-notification/trigger', {
        preset_id: preset.id,
        title: preset.title,
        message: preset.message,
        category: preset.category,
        delay_seconds: delay,
        trigger_method: 'dashboard',
      });
      const data = res.data;

      if (delay > 0) {
        toast.success(`Notification scheduled in ${delay}s`, { description: preset.title, duration: delay * 1000 });
        setTimeout(() => {
          onNotification?.({
            notification_id: data.notification_id,
            title: preset.title,
            message: preset.message,
            category: preset.category,
            icon_style: preset.icon_style,
          });
        }, delay * 1000);
      } else {
        onNotification?.({
          notification_id: data.notification_id,
          title: preset.title,
          message: preset.message,
          category: preset.category,
          icon_style: preset.icon_style,
        });
      }
      fetchData();
    } catch {
      toast.error('Failed to trigger notification');
    } finally {
      setTriggerLoading(false);
    }
  };

  const handleCreatePreset = async () => {
    if (!newPreset.title.trim()) return;
    try {
      await api.post('/fake-notification/presets', newPreset);
      setNewPreset({ title: '', message: '', category: 'Custom', icon_style: 'default' });
      setShowCreate(false);
      fetchData();
      toast.success('Notification preset created');
    } catch {
      toast.error('Failed to create preset');
    }
  };

  const handleDeletePreset = async (id) => {
    try {
      await api.delete(`/fake-notification/presets/${id}`);
      fetchData();
      toast.success('Preset deleted');
    } catch {
      toast.error('Cannot delete default preset');
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64" data-testid="fake-notif-loading">
        <Loader2 className="w-8 h-8 animate-spin text-teal-600" />
      </div>
    );
  }

  return (
    <div className="space-y-6" data-testid="fake-notification-page">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-black text-slate-800 flex items-center gap-2">
            <BellRing className="w-6 h-6 text-teal-600" />
            Escape Notification
          </h1>
          <p className="text-sm text-slate-500 mt-1">Trigger realistic push notifications to create an excuse to leave</p>
        </div>
        <Button variant="outline" size="sm" onClick={() => setShowCreate(!showCreate)} className="text-xs" data-testid="add-notif-preset-btn">
          <Plus className="w-3.5 h-3.5 mr-1" /> New Notification
        </Button>
      </div>

      {/* Info Banner */}
      <div className="p-3 bg-violet-50 border border-violet-200 rounded-lg flex items-start gap-2" data-testid="notif-info-banner">
        <Shield className="w-4 h-4 text-violet-600 mt-0.5 flex-shrink-0" />
        <div className="text-xs text-violet-700">
          <span className="font-bold">How it works:</span> Select a notification type and tap Send.
          A realistic notification banner will appear at the top of the screen — giving you a natural excuse to check your phone and leave.
        </div>
      </div>

      {/* Create New Preset */}
      {showCreate && (
        <Card className="border-dashed border-2 border-teal-300" data-testid="create-notif-preset-form">
          <CardContent className="p-4">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className="text-[10px] text-slate-500 font-semibold uppercase">Title</label>
                <input
                  value={newPreset.title}
                  onChange={e => setNewPreset(p => ({ ...p, title: e.target.value }))}
                  placeholder="e.g. Doctor Appointment Reminder"
                  className="mt-1 w-full px-3 py-2 text-sm border rounded-lg focus:outline-none focus:ring-2 focus:ring-teal-400"
                  data-testid="new-notif-title"
                />
              </div>
              <div>
                <label className="text-[10px] text-slate-500 font-semibold uppercase">Category</label>
                <select
                  value={newPreset.category}
                  onChange={e => setNewPreset(p => ({ ...p, category: e.target.value }))}
                  className="mt-1 w-full px-3 py-2 text-sm border rounded-lg focus:outline-none focus:ring-2 focus:ring-teal-400"
                  data-testid="new-notif-category"
                >
                  {Object.keys(CATEGORY_META).map(c => <option key={c} value={c}>{c}</option>)}
                </select>
              </div>
            </div>
            <div className="mt-3">
              <label className="text-[10px] text-slate-500 font-semibold uppercase">Message</label>
              <textarea
                value={newPreset.message}
                onChange={e => setNewPreset(p => ({ ...p, message: e.target.value }))}
                placeholder="The notification body text..."
                rows={2}
                className="mt-1 w-full px-3 py-2 text-sm border rounded-lg focus:outline-none focus:ring-2 focus:ring-teal-400 resize-none"
                data-testid="new-notif-message"
              />
            </div>
            <div className="flex gap-2 mt-3 justify-end">
              <Button variant="outline" size="sm" onClick={() => setShowCreate(false)} data-testid="cancel-notif-preset-btn">Cancel</Button>
              <Button size="sm" onClick={handleCreatePreset} className="bg-teal-600 hover:bg-teal-700 text-white" data-testid="save-notif-preset-btn">Save Notification</Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Preset Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4" data-testid="notif-presets-grid">
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

      {/* History */}
      <Card data-testid="notif-history-card">
        <CardHeader className="pb-2 cursor-pointer" onClick={() => setShowHistory(!showHistory)}>
          <CardTitle className="text-sm font-bold text-slate-700 flex items-center gap-2">
            <History className="w-4 h-4" /> Notification History ({history.length})
            {showHistory ? <ChevronUp className="w-4 h-4 ml-auto" /> : <ChevronDown className="w-4 h-4 ml-auto" />}
          </CardTitle>
        </CardHeader>
        {showHistory && (
          <CardContent>
            {history.length === 0 ? (
              <p className="text-xs text-slate-400 text-center py-4">No notifications yet</p>
            ) : (
              <div className="space-y-2">
                {history.map(h => {
                  const meta = CATEGORY_META[h.category] || CATEGORY_META.Custom;
                  const Icon = meta.icon;
                  return (
                    <div key={h.id} className="flex items-center gap-3 p-2 rounded-lg bg-slate-50 border" data-testid={`notif-history-${h.id}`}>
                      <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ background: `${meta.accent}15` }}>
                        <Icon className="w-4 h-4" style={{ color: meta.accent }} />
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="text-xs font-bold text-slate-700 truncate">{h.title}</div>
                        <div className="text-[10px] text-slate-400">
                          {new Date(h.triggered_at).toLocaleString()} | {h.trigger_method}
                        </div>
                      </div>
                      <div className="flex items-center gap-1">
                        {h.viewed && <Badge className="bg-blue-100 text-blue-700 text-[9px]">Viewed</Badge>}
                        {h.alert_sent && <Badge className="bg-amber-100 text-amber-700 text-[9px]">Alert</Badge>}
                        <Badge className={`text-[9px] ${h.status === 'completed' ? 'bg-green-100 text-green-700' : 'bg-slate-100 text-slate-600'}`}>
                          {h.status}
                        </Badge>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </CardContent>
        )}
      </Card>
    </div>
  );
};

export default FakeNotificationPage;
