import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../../api';
import { toast } from 'sonner';
import {
  Bell, AlertTriangle, Shield, MapPin, Clock, RefreshCw,
  Loader2, Inbox, Activity, FileText, CheckCircle,
} from 'lucide-react';

const SEVERITY_STYLES = {
  critical: { bg: 'bg-red-500/10', border: 'border-red-500/30', icon: 'text-red-400', dot: 'bg-red-400' },
  high: { bg: 'bg-orange-500/10', border: 'border-orange-500/30', icon: 'text-orange-400', dot: 'bg-orange-400' },
  medium: { bg: 'bg-amber-500/10', border: 'border-amber-500/30', icon: 'text-amber-400', dot: 'bg-amber-400' },
  low: { bg: 'bg-slate-500/10', border: 'border-slate-700/30', icon: 'text-slate-400', dot: 'bg-slate-400' },
};

const ALERT_ICONS = {
  fall_detected: AlertTriangle,
  voice_distress: Activity,
  route_deviation: MapPin,
  sos: Shield,
  wandering: MapPin,
};

function timeAgo(dateStr) {
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'Just now';
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export default function MobileAlerts() {
  const navigate = useNavigate();
  const [alerts, setAlerts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const fetchAlerts = useCallback(async () => {
    try {
      const res = await api.get('/safety-events/guardian-alerts?limit=30');
      setAlerts(res.data.alerts || []);
    } catch { /* silent */ }
    setLoading(false);
    setRefreshing(false);
  }, []);

  useEffect(() => {
    fetchAlerts();
    const iv = setInterval(fetchAlerts, 15000);
    return () => clearInterval(iv);
  }, [fetchAlerts]);

  const refresh = () => {
    setRefreshing(true);
    fetchAlerts();
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="w-8 h-8 text-teal-400 animate-spin" />
      </div>
    );
  }

  return (
    <div className="px-4 pt-4 pb-6" data-testid="mobile-alerts">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-lg font-bold text-white">Alerts</h1>
          <p className="text-[11px] text-slate-500">{alerts.length} recent alerts</p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={refresh}
            className="p-2 rounded-full bg-slate-800/50 active:bg-slate-700/50"
            data-testid="refresh-alerts-btn"
          >
            <RefreshCw className={`w-4 h-4 text-slate-400 ${refreshing ? 'animate-spin' : ''}`} />
          </button>
          <button
            onClick={() => navigate('/m/incidents')}
            className="p-2 rounded-full bg-violet-500/15 active:bg-violet-500/25"
            data-testid="incident-replay-btn"
          >
            <FileText className="w-4 h-4 text-violet-400" />
          </button>
        </div>
      </div>

      {/* Alert List */}
      {alerts.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 text-center">
          <Inbox className="w-12 h-12 text-slate-700 mb-3" />
          <p className="text-sm text-slate-500 font-medium">No alerts yet</p>
          <p className="text-xs text-slate-600 mt-1">When safety events occur, they'll appear here</p>
        </div>
      ) : (
        <div className="space-y-2" data-testid="alerts-list">
          {alerts.map((alert) => {
            const sev = SEVERITY_STYLES[alert.severity] || SEVERITY_STYLES.low;
            const Icon = ALERT_ICONS[alert.alert_type] || Bell;

            return (
              <div
                key={alert.id}
                className={`p-3 rounded-2xl ${sev.bg} border ${sev.border} transition-all`}
                data-testid={`alert-${alert.id}`}
              >
                <div className="flex items-start gap-3">
                  <div className={`mt-0.5 w-8 h-8 rounded-full ${sev.bg} flex items-center justify-center shrink-0`}>
                    <Icon className={`w-4 h-4 ${sev.icon}`} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-0.5">
                      <span className={`text-[10px] font-bold uppercase ${sev.icon}`}>
                        {alert.alert_type?.replace(/_/g, ' ')}
                      </span>
                      <span className={`w-1.5 h-1.5 rounded-full ${sev.dot}`} />
                      <span className="text-[10px] text-slate-500 uppercase">{alert.severity}</span>
                    </div>
                    <p className="text-xs text-slate-300 leading-relaxed">{alert.message}</p>
                    {alert.recommendation && (
                      <p className="text-[10px] text-slate-500 mt-1 italic">{alert.recommendation}</p>
                    )}
                    <div className="flex items-center gap-3 mt-1.5">
                      <span className="text-[9px] text-slate-600 flex items-center gap-1">
                        <Clock className="w-3 h-3" /> {timeAgo(alert.created_at)}
                      </span>
                      {alert.location?.lat && (
                        <span className="text-[9px] text-slate-600 flex items-center gap-1">
                          <MapPin className="w-3 h-3" /> {alert.location.lat.toFixed(3)}, {alert.location.lng.toFixed(3)}
                        </span>
                      )}
                    </div>
                    {alert.incident_id && alert.status !== 'acknowledged' && alert.status !== 'resolved' && (
                      <button
                        onClick={async (e) => {
                          e.stopPropagation();
                          try {
                            await api.patch(`/incidents/${alert.incident_id}/acknowledge?channel=mobile`);
                            toast.success('Incident acknowledged');
                            fetchAlerts();
                          } catch {
                            toast.error('Failed to acknowledge');
                          }
                        }}
                        className="mt-2 w-full flex items-center justify-center gap-1.5 py-2 rounded-xl bg-teal-500/15 border border-teal-500/30 text-teal-400 text-xs font-semibold active:bg-teal-500/25 transition-colors"
                        data-testid="mobile-acknowledge-btn"
                      >
                        <CheckCircle className="w-3.5 h-3.5" /> Acknowledge Incident
                      </button>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
