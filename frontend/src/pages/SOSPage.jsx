import React, { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import {
  ShieldAlert, Settings, History, Loader2, ChevronDown, ChevronUp,
  Phone, BellRing, MapPin, Mic, Clock, CheckCircle, XCircle,
  AlertTriangle, Save, Link2, Users, Volume2, Eye, Zap,
} from 'lucide-react';
import api from '../api';
import { toast } from 'sonner';

const TRIGGER_ICONS = {
  manual: ShieldAlert,
  widget: Zap,
  voice: Mic,
  shake: Phone,
  dashboard: Settings,
};

const SOSPage = ({ activeSOS, onTriggerSOS }) => {
  const [config, setConfig] = useState(null);
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [editConfig, setEditConfig] = useState(null);
  const [triggerLoading, setTriggerLoading] = useState(false);

  const fetchData = useCallback(async () => {
    try {
      const [cfgRes, histRes] = await Promise.all([
        api.get('/sos/config'),
        api.get('/sos/history?limit=15'),
      ]);
      setConfig(cfgRes.data);
      setEditConfig(cfgRes.data);
      setHistory(histRes.data?.history || []);
    } catch {
      toast.error('Failed to load SOS settings');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handleSave = async () => {
    if (!editConfig) return;
    setSaving(true);
    try {
      const res = await api.put('/sos/config', {
        enabled: editConfig.enabled,
        voice_keywords: editConfig.voice_keywords,
        chain_notification: editConfig.chain_notification,
        chain_notification_delay: editConfig.chain_notification_delay,
        chain_call: editConfig.chain_call,
        chain_call_delay: editConfig.chain_call_delay,
        chain_call_preset_name: editConfig.chain_call_preset_name,
        chain_notification_title: editConfig.chain_notification_title,
        chain_notification_message: editConfig.chain_notification_message,
        trusted_contacts: editConfig.trusted_contacts,
        auto_share_location: editConfig.auto_share_location,
        silent_mode: editConfig.silent_mode,
      });
      setConfig(res.data);
      toast.success('SOS configuration saved');
    } catch {
      toast.error('Failed to save configuration');
    } finally {
      setSaving(false);
    }
  };

  const handleTrigger = async () => {
    setTriggerLoading(true);
    try {
      const res = await api.post('/sos/trigger', {
        trigger_type: 'dashboard',
        lat: 28.6139,
        lng: 77.2090,
      });
      onTriggerSOS?.(res.data);
      toast.warning('SOS TRIGGERED', { description: 'Silent alert sent. Chain sequence initiated.', duration: 10000 });
      fetchData();
    } catch {
      toast.error('Failed to trigger SOS');
    } finally {
      setTriggerLoading(false);
    }
  };

  const handleCancel = async (sosId) => {
    try {
      await api.post(`/sos/cancel/${sosId}`, { resolved_by: 'user' });
      toast.success('SOS resolved');
      fetchData();
    } catch {
      toast.error('Failed to cancel SOS');
    }
  };

  const updateField = (key, value) => setEditConfig(prev => ({ ...prev, [key]: value }));

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64" data-testid="sos-loading">
        <Loader2 className="w-8 h-8 animate-spin text-red-600" />
      </div>
    );
  }

  return (
    <div className="space-y-6" data-testid="sos-page">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-black text-slate-800 flex items-center gap-2">
            <ShieldAlert className="w-6 h-6 text-red-600" />
            SOS Silent Mode
          </h1>
          <p className="text-sm text-slate-500 mt-1">Covert emergency trigger with auto-chain escape sequence</p>
        </div>
        <Button onClick={handleSave} disabled={saving} size="sm" className="bg-teal-600 hover:bg-teal-700 text-white text-xs" data-testid="save-sos-config-btn">
          {saving ? <Loader2 className="w-3.5 h-3.5 mr-1 animate-spin" /> : <Save className="w-3.5 h-3.5 mr-1" />}
          Save Config
        </Button>
      </div>

      {/* Active SOS Alert */}
      {activeSOS && activeSOS.status === 'active' && (
        <div className="p-4 bg-red-50 border-2 border-red-300 rounded-xl animate-pulse" data-testid="active-sos-banner">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <ShieldAlert className="w-6 h-6 text-red-600" />
              <div>
                <div className="font-bold text-red-800">SOS ACTIVE</div>
                <div className="text-xs text-red-600">Triggered at {new Date(activeSOS.triggered_at).toLocaleTimeString()} via {activeSOS.trigger_type}</div>
              </div>
            </div>
            <Button variant="outline" size="sm" onClick={() => handleCancel(activeSOS.sos_id)} className="border-red-300 text-red-700 hover:bg-red-100" data-testid="cancel-active-sos-btn">
              <XCircle className="w-4 h-4 mr-1" /> Cancel SOS
            </Button>
          </div>
          {activeSOS.chain && (
            <div className="mt-3 flex items-center gap-4 text-xs text-red-700">
              {activeSOS.chain.notification && (
                <span className="flex items-center gap-1"><BellRing className="w-3 h-3" /> Notification in {activeSOS.chain.notification.delay_seconds}s</span>
              )}
              {activeSOS.chain.call && (
                <span className="flex items-center gap-1"><Phone className="w-3 h-3" /> Call from "{activeSOS.chain.call.caller_name}" in {activeSOS.chain.call.delay_seconds}s</span>
              )}
            </div>
          )}
        </div>
      )}

      {/* SOS Trigger Widget */}
      <Card className="border-red-200 bg-gradient-to-br from-red-50 to-white" data-testid="sos-trigger-card">
        <CardContent className="p-6 flex flex-col items-center">
          <button
            onClick={handleTrigger}
            disabled={triggerLoading || (activeSOS && activeSOS.status === 'active')}
            className="w-32 h-32 rounded-full bg-red-600 hover:bg-red-700 active:scale-95 flex items-center justify-center shadow-xl shadow-red-600/30 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
            data-testid="sos-trigger-widget"
          >
            {triggerLoading ? (
              <Loader2 className="w-10 h-10 text-white animate-spin" />
            ) : (
              <ShieldAlert className="w-10 h-10 text-white" />
            )}
          </button>
          <div className="text-sm font-bold text-red-800 mt-3">Press to Trigger Silent SOS</div>
          <div className="text-[10px] text-red-500 mt-1">Long-press on mobile for hands-free activation</div>
          <div className="flex items-center gap-4 mt-4 text-xs text-slate-500">
            <span className="flex items-center gap-1">
              <MapPin className="w-3 h-3" /> Location shared
            </span>
            <span className="flex items-center gap-1">
              <Users className="w-3 h-3" /> Contacts alerted
            </span>
            <span className="flex items-center gap-1">
              <Link2 className="w-3 h-3" /> Chain activated
            </span>
          </div>
        </CardContent>
      </Card>

      {/* Configuration */}
      {editConfig && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* Chain Settings */}
          <Card data-testid="chain-config-card">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-bold text-slate-700 flex items-center gap-2">
                <Link2 className="w-4 h-4 text-teal-600" /> Chain Escape Sequence
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {/* Chain Notification */}
              <div className="p-3 rounded-lg border bg-slate-50">
                <label className="flex items-center justify-between cursor-pointer">
                  <span className="flex items-center gap-2 text-xs font-bold text-slate-700">
                    <BellRing className="w-4 h-4 text-violet-500" />
                    Step 1: Auto Fake Notification
                  </span>
                  <input
                    type="checkbox"
                    checked={editConfig.chain_notification}
                    onChange={e => updateField('chain_notification', e.target.checked)}
                    className="w-4 h-4 rounded text-teal-600"
                    data-testid="chain-notif-toggle"
                  />
                </label>
                {editConfig.chain_notification && (
                  <div className="mt-2 space-y-2">
                    <div className="flex items-center gap-2">
                      <Clock className="w-3 h-3 text-slate-400" />
                      <span className="text-[10px] text-slate-500">Delay:</span>
                      <input type="number" min="0" max="120"
                        value={editConfig.chain_notification_delay}
                        onChange={e => updateField('chain_notification_delay', parseInt(e.target.value) || 0)}
                        className="w-16 px-2 py-1 text-xs border rounded" data-testid="chain-notif-delay" />
                      <span className="text-[10px] text-slate-400">seconds</span>
                    </div>
                    <input value={editConfig.chain_notification_title}
                      onChange={e => updateField('chain_notification_title', e.target.value)}
                      placeholder="Notification title"
                      className="w-full px-2 py-1 text-xs border rounded" data-testid="chain-notif-title" />
                  </div>
                )}
              </div>

              {/* Chain Call */}
              <div className="p-3 rounded-lg border bg-slate-50">
                <label className="flex items-center justify-between cursor-pointer">
                  <span className="flex items-center gap-2 text-xs font-bold text-slate-700">
                    <Phone className="w-4 h-4 text-blue-500" />
                    Step 2: Auto Fake Call
                  </span>
                  <input
                    type="checkbox"
                    checked={editConfig.chain_call}
                    onChange={e => updateField('chain_call', e.target.checked)}
                    className="w-4 h-4 rounded text-teal-600"
                    data-testid="chain-call-toggle"
                  />
                </label>
                {editConfig.chain_call && (
                  <div className="mt-2 space-y-2">
                    <div className="flex items-center gap-2">
                      <Clock className="w-3 h-3 text-slate-400" />
                      <span className="text-[10px] text-slate-500">Delay:</span>
                      <input type="number" min="0" max="300"
                        value={editConfig.chain_call_delay}
                        onChange={e => updateField('chain_call_delay', parseInt(e.target.value) || 0)}
                        className="w-16 px-2 py-1 text-xs border rounded" data-testid="chain-call-delay" />
                      <span className="text-[10px] text-slate-400">seconds</span>
                    </div>
                    <input value={editConfig.chain_call_preset_name}
                      onChange={e => updateField('chain_call_preset_name', e.target.value)}
                      placeholder="Caller name (e.g. Boss)"
                      className="w-full px-2 py-1 text-xs border rounded" data-testid="chain-call-name" />
                  </div>
                )}
              </div>
            </CardContent>
          </Card>

          {/* Detection & Keywords */}
          <Card data-testid="detection-config-card">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-bold text-slate-700 flex items-center gap-2">
                <Mic className="w-4 h-4 text-teal-600" /> Voice Keywords & Settings
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {/* Enable/Disable */}
              <label className="flex items-center justify-between p-3 rounded-lg border bg-slate-50 cursor-pointer">
                <span className="text-xs font-bold text-slate-700">SOS Enabled</span>
                <input type="checkbox" checked={editConfig.enabled}
                  onChange={e => updateField('enabled', e.target.checked)}
                  className="w-4 h-4 rounded text-teal-600" data-testid="sos-enabled-toggle" />
              </label>

              {/* Silent Mode */}
              <label className="flex items-center justify-between p-3 rounded-lg border bg-slate-50 cursor-pointer">
                <span className="flex items-center gap-2 text-xs font-bold text-slate-700">
                  <Eye className="w-3.5 h-3.5 text-slate-400" /> Silent Mode (no visible feedback)
                </span>
                <input type="checkbox" checked={editConfig.silent_mode}
                  onChange={e => updateField('silent_mode', e.target.checked)}
                  className="w-4 h-4 rounded text-teal-600" data-testid="silent-mode-toggle" />
              </label>

              {/* Auto Share Location */}
              <label className="flex items-center justify-between p-3 rounded-lg border bg-slate-50 cursor-pointer">
                <span className="flex items-center gap-2 text-xs font-bold text-slate-700">
                  <MapPin className="w-3.5 h-3.5 text-slate-400" /> Auto-share location
                </span>
                <input type="checkbox" checked={editConfig.auto_share_location}
                  onChange={e => updateField('auto_share_location', e.target.checked)}
                  className="w-4 h-4 rounded text-teal-600" data-testid="auto-location-toggle" />
              </label>

              {/* Voice Keywords */}
              <div className="p-3 rounded-lg border bg-slate-50">
                <div className="flex items-center gap-2 mb-2">
                  <Volume2 className="w-3.5 h-3.5 text-slate-400" />
                  <span className="text-xs font-bold text-slate-700">Voice Trigger Keywords</span>
                </div>
                <div className="flex flex-wrap gap-1">
                  {(editConfig.voice_keywords || []).map((kw, i) => (
                    <Badge key={i} variant="outline" className="text-[10px] px-2 py-1" data-testid={`voice-keyword-${i}`}>
                      "{kw}"
                      <button onClick={() => updateField('voice_keywords', editConfig.voice_keywords.filter((_, j) => j !== i))}
                        className="ml-1 text-slate-400 hover:text-red-500">&times;</button>
                    </Badge>
                  ))}
                </div>
                <div className="flex gap-1 mt-2">
                  <input id="new-keyword" placeholder="Add keyword..."
                    className="flex-1 px-2 py-1 text-xs border rounded" data-testid="new-keyword-input"
                    onKeyDown={e => {
                      if (e.key === 'Enter' && e.target.value.trim()) {
                        updateField('voice_keywords', [...(editConfig.voice_keywords || []), e.target.value.trim()]);
                        e.target.value = '';
                      }
                    }} />
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* SOS History */}
      <Card data-testid="sos-history-card">
        <CardHeader className="pb-2 cursor-pointer" onClick={() => setShowHistory(!showHistory)}>
          <CardTitle className="text-sm font-bold text-slate-700 flex items-center gap-2">
            <History className="w-4 h-4" /> SOS History ({history.length})
            {showHistory ? <ChevronUp className="w-4 h-4 ml-auto" /> : <ChevronDown className="w-4 h-4 ml-auto" />}
          </CardTitle>
        </CardHeader>
        {showHistory && (
          <CardContent>
            {history.length === 0 ? (
              <p className="text-xs text-slate-400 text-center py-4">No SOS events</p>
            ) : (
              <div className="space-y-2">
                {history.map(h => {
                  const Icon = TRIGGER_ICONS[h.trigger_type] || ShieldAlert;
                  const isActive = h.status === 'active';
                  return (
                    <div key={h.id} className={`flex items-center gap-3 p-3 rounded-lg border ${isActive ? 'bg-red-50 border-red-200' : 'bg-slate-50'}`} data-testid={`sos-event-${h.id}`}>
                      <div className={`w-9 h-9 rounded-full flex items-center justify-center ${isActive ? 'bg-red-100' : 'bg-green-100'}`}>
                        <Icon className={`w-4 h-4 ${isActive ? 'text-red-600' : 'text-green-600'}`} />
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="text-xs font-bold text-slate-700">{h.trigger_type}</span>
                          <Badge className={`text-[9px] ${isActive ? 'bg-red-100 text-red-700' : 'bg-green-100 text-green-700'}`}>
                            {h.status}
                          </Badge>
                        </div>
                        <div className="text-[10px] text-slate-400">
                          {new Date(h.triggered_at).toLocaleString()}
                          {h.resolved_at && ` | Resolved: ${new Date(h.resolved_at).toLocaleTimeString()}`}
                          {h.resolved_by && ` by ${h.resolved_by}`}
                        </div>
                        <div className="flex gap-2 mt-0.5">
                          {h.chain_notification_triggered && <span className="text-[9px] text-violet-500 flex items-center gap-0.5"><BellRing className="w-2.5 h-2.5" /> Notif</span>}
                          {h.chain_call_triggered && <span className="text-[9px] text-blue-500 flex items-center gap-0.5"><Phone className="w-2.5 h-2.5" /> Call</span>}
                          {h.lat && <span className="text-[9px] text-slate-400 flex items-center gap-0.5"><MapPin className="w-2.5 h-2.5" /> {h.lat.toFixed(4)}, {h.lng?.toFixed(4)}</span>}
                        </div>
                      </div>
                      {isActive && (
                        <Button variant="outline" size="sm" onClick={() => handleCancel(h.id)} className="text-[10px] border-red-200 text-red-600" data-testid={`cancel-sos-${h.id}`}>
                          Cancel
                        </Button>
                      )}
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

export default SOSPage;
