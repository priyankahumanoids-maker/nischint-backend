import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowLeft, Bell, BellOff, CheckCircle, AlertTriangle, Shield, Users, MapPin, Loader2 } from 'lucide-react';
import api from '../../api';

const TAG_CONFIG = {
  'nischint-sos': { icon: Shield, color: 'text-red-400', bg: 'bg-red-500/10', label: 'SOS' },
  'nischint-risk': { icon: AlertTriangle, color: 'text-amber-400', bg: 'bg-amber-500/10', label: 'Risk' },
  'nischint-invite': { icon: Users, color: 'text-teal-400', bg: 'bg-teal-500/10', label: 'Invite' },
  'nischint-session': { icon: MapPin, color: 'text-blue-400', bg: 'bg-blue-500/10', label: 'Session' },
  'nischint-incident': { icon: AlertTriangle, color: 'text-orange-400', bg: 'bg-orange-500/10', label: 'Incident' },
  'nischint-guardian': { icon: Users, color: 'text-purple-400', bg: 'bg-purple-500/10', label: 'Guardian' },
};

function timeAgo(dateStr) {
  if (!dateStr) return '';
  const diff = (Date.now() - new Date(dateStr).getTime()) / 1000;
  if (diff < 60) return 'just now';
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

export default function MobileNotifications() {
  const navigate = useNavigate();
  const [notifications, setNotifications] = useState([]);
  const [pushStatus, setPushStatus] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    try {
      const [notifRes, statusRes] = await Promise.all([
        api.get('/device/notifications?limit=50'),
        api.get('/device/push-status'),
      ]);
      setNotifications(notifRes.data?.notifications || []);
      setPushStatus(statusRes.data);
    } catch (err) {
      console.warn('Failed to load notifications:', err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  const markRead = async (id) => {
    try {
      await api.put(`/device/notifications/${id}/read`);
      setNotifications(prev => prev.map(n => n.id === id ? { ...n, is_read: true } : n));
    } catch {}
  };

  return (
    <div className="px-4 py-3 pb-24" data-testid="mobile-notifications">
      {/* Header */}
      <div className="flex items-center gap-3 mb-5">
        <button onClick={() => navigate(-1)} className="p-1.5 rounded-xl bg-slate-800/60" data-testid="notifications-back-btn">
          <ArrowLeft className="w-5 h-5 text-slate-400" />
        </button>
        <h1 className="text-lg font-semibold">Notifications</h1>
      </div>

      {/* Push Status Card */}
      {pushStatus && (
        <div className="bg-slate-900/80 border border-slate-800/60 rounded-2xl p-4 mb-5" data-testid="push-status-card">
          <div className="flex items-center gap-3">
            {pushStatus.push_enabled ? (
              <div className="w-10 h-10 rounded-full bg-teal-500/15 flex items-center justify-center">
                <Bell className="w-5 h-5 text-teal-400" />
              </div>
            ) : (
              <div className="w-10 h-10 rounded-full bg-slate-700/50 flex items-center justify-center">
                <BellOff className="w-5 h-5 text-slate-500" />
              </div>
            )}
            <div className="flex-1">
              <p className="text-sm font-medium">
                Push Notifications: {' '}
                <span className={pushStatus.push_enabled ? 'text-teal-400' : 'text-slate-500'}>
                  {pushStatus.push_enabled ? 'Active' : 'Not Registered'}
                </span>
              </p>
              <p className="text-xs text-slate-500">
                {pushStatus.fcm_active ? 'Firebase connected' : 'Firebase inactive'} · {pushStatus.devices_registered} device(s)
              </p>
            </div>
            {pushStatus.push_enabled && (
              <CheckCircle className="w-5 h-5 text-teal-400" />
            )}
          </div>
        </div>
      )}

      {/* Notification List */}
      {loading ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="w-6 h-6 text-teal-400 animate-spin" />
        </div>
      ) : notifications.length === 0 ? (
        <div className="text-center py-16" data-testid="no-notifications">
          <Bell className="w-10 h-10 text-slate-700 mx-auto mb-3" />
          <p className="text-slate-500 text-sm">No notifications yet</p>
          <p className="text-slate-600 text-xs mt-1">Safety alerts and updates will appear here</p>
        </div>
      ) : (
        <div className="space-y-2">
          {notifications.map(n => {
            const config = TAG_CONFIG[n.tag] || TAG_CONFIG['nischint-guardian'];
            const Icon = config.icon;
            return (
              <button
                key={n.id}
                onClick={() => !n.is_read && markRead(n.id)}
                className={`w-full text-left p-3 rounded-xl border transition-colors ${
                  n.is_read
                    ? 'bg-slate-900/40 border-slate-800/40'
                    : 'bg-slate-900/80 border-slate-700/60'
                }`}
                data-testid={`notification-${n.id}`}
              >
                <div className="flex items-start gap-3">
                  <div className={`w-9 h-9 rounded-xl ${config.bg} flex items-center justify-center shrink-0 mt-0.5`}>
                    <Icon className={`w-4 h-4 ${config.color}`} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <p className={`text-sm font-medium truncate ${n.is_read ? 'text-slate-400' : 'text-slate-200'}`}>
                        {n.title}
                      </p>
                      {!n.is_read && (
                        <span className="w-2 h-2 rounded-full bg-teal-400 shrink-0" />
                      )}
                    </div>
                    <p className={`text-xs mt-0.5 line-clamp-2 ${n.is_read ? 'text-slate-600' : 'text-slate-400'}`}>
                      {n.body}
                    </p>
                    <div className="flex items-center gap-2 mt-1">
                      <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${config.bg} ${config.color}`}>
                        {config.label}
                      </span>
                      <span className="text-[10px] text-slate-600">{timeAgo(n.created_at)}</span>
                    </div>
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
