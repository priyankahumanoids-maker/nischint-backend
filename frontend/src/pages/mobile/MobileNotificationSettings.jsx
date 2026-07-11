import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowLeft, Shield, Bell, Users, AlertTriangle, FileText, Loader2, Lock } from 'lucide-react';
import api from '../../api';

function Toggle({ enabled, onToggle, locked, testId }) {
  return (
    <button
      onClick={locked ? undefined : onToggle}
      className={`w-11 h-6 rounded-full transition-colors relative ${
        locked ? 'bg-teal-600 cursor-not-allowed' : enabled ? 'bg-teal-500' : 'bg-slate-700'
      }`}
      disabled={locked}
      data-testid={testId}
    >
      <div className={`w-5 h-5 rounded-full bg-white shadow-sm absolute top-0.5 transition-transform ${
        enabled || locked ? 'translate-x-[22px]' : 'translate-x-0.5'
      }`} />
    </button>
  );
}

export default function MobileNotificationSettings() {
  const navigate = useNavigate();
  const [prefs, setPrefs] = useState({
    general_notifications: true,
    guardian_alerts: true,
    incident_updates: true,
    daily_summary: false,
    push_enabled: true,
    sms_enabled: true,
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const res = await api.get('/settings/notifications');
        setPrefs(res.data);
      } catch (e) {
        console.error('Failed to load notification prefs:', e);
      }
      setLoading(false);
    })();
  }, []);

  const togglePref = async (key) => {
    const updated = { ...prefs, [key]: !prefs[key] };
    setPrefs(updated);
    setSaving(true);
    try {
      await api.put('/settings/notifications', { [key]: updated[key] });
    } catch (e) {
      // Revert on failure
      setPrefs(prefs);
      console.error('Failed to save notification pref:', e);
    }
    setSaving(false);
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-6 h-6 text-teal-400 animate-spin" />
      </div>
    );
  }

  return (
    <div className="px-4 pt-4 pb-6" data-testid="notification-settings">
      {/* Header */}
      <div className="flex items-center gap-3 mb-6">
        <button onClick={() => navigate(-1)} className="p-1" data-testid="notif-back">
          <ArrowLeft className="w-5 h-5 text-slate-400" />
        </button>
        <h1 className="text-base font-semibold text-white">Notification Settings</h1>
        {saving && <Loader2 className="w-3.5 h-3.5 text-teal-400 animate-spin ml-auto" />}
      </div>

      {/* Critical Safety Alerts — Always ON */}
      <div className="mb-5">
        <h2 className="text-[10px] text-red-400 uppercase font-bold tracking-wider mb-2 px-1 flex items-center gap-1.5">
          <Lock className="w-3 h-3" /> Mandatory
        </h2>
        <div className="p-4 rounded-2xl bg-red-500/5 border border-red-500/15">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-red-500/10 flex items-center justify-center">
              <Shield className="w-4.5 h-4.5 text-red-400" />
            </div>
            <div className="flex-1">
              <p className="text-sm font-semibold text-white">Critical Safety Alerts</p>
              <p className="text-[10px] text-slate-500 mt-0.5">SOS alerts, guardian emergencies, high-risk anomalies</p>
            </div>
            <Toggle enabled locked testId="toggle-critical" />
          </div>
          <p className="text-[9px] text-red-400/60 mt-2 ml-12">Always ON — cannot be disabled for your safety</p>
        </div>
      </div>

      {/* Optional Toggles */}
      <div className="mb-5">
        <h2 className="text-[10px] text-slate-500 uppercase font-bold tracking-wider mb-2 px-1">Alert Categories</h2>
        <div className="space-y-2">
          <SettingRow
            icon={<Bell className="w-4 h-4 text-teal-400" />}
            label="General Notifications"
            desc="Platform updates, tips, and general information"
            enabled={prefs.general_notifications}
            onToggle={() => togglePref('general_notifications')}
            testId="toggle-general"
          />
          <SettingRow
            icon={<Users className="w-4 h-4 text-blue-400" />}
            label="Guardian Alerts"
            desc="Guardian location updates and status changes"
            enabled={prefs.guardian_alerts}
            onToggle={() => togglePref('guardian_alerts')}
            testId="toggle-guardian"
          />
          <SettingRow
            icon={<AlertTriangle className="w-4 h-4 text-amber-400" />}
            label="Incident Updates"
            desc="Status updates for ongoing and resolved incidents"
            enabled={prefs.incident_updates}
            onToggle={() => togglePref('incident_updates')}
            testId="toggle-incidents"
          />
          <SettingRow
            icon={<FileText className="w-4 h-4 text-violet-400" />}
            label="Daily Safety Summary"
            desc="Daily digest of safety activity and risk insights"
            enabled={prefs.daily_summary}
            onToggle={() => togglePref('daily_summary')}
            testId="toggle-summary"
          />
        </div>
      </div>

      {/* Delivery Channels */}
      <div className="mb-5">
        <h2 className="text-[10px] text-slate-500 uppercase font-bold tracking-wider mb-2 px-1">Delivery Channels</h2>
        <div className="space-y-2">
          <SettingRow
            icon={<Bell className="w-4 h-4 text-emerald-400" />}
            label="Push Notifications"
            desc="Receive alerts on your device"
            enabled={prefs.push_enabled}
            onToggle={() => togglePref('push_enabled')}
            testId="toggle-push"
          />
          <SettingRow
            icon={<Bell className="w-4 h-4 text-cyan-400" />}
            label="SMS Alerts"
            desc="Receive critical alerts via text message"
            enabled={prefs.sms_enabled}
            onToggle={() => togglePref('sms_enabled')}
            testId="toggle-sms"
          />
        </div>
      </div>

      <p className="text-center text-[9px] text-slate-600 mt-4">
        Critical safety alerts are always active to ensure your protection.
      </p>
    </div>
  );
}

function SettingRow({ icon, label, desc, enabled, onToggle, testId }) {
  return (
    <div className="p-3.5 rounded-xl bg-slate-800/30 border border-slate-700/30 flex items-center gap-3" data-testid={`row-${testId}`}>
      <div className="w-8 h-8 rounded-lg bg-slate-800/50 flex items-center justify-center shrink-0">
        {icon}
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-xs font-medium text-white">{label}</p>
        <p className="text-[9px] text-slate-500 mt-0.5">{desc}</p>
      </div>
      <Toggle enabled={enabled} onToggle={onToggle} testId={testId} />
    </div>
  );
}
