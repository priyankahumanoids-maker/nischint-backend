import React from 'react';
import { Radio, AlertTriangle, MapPin, Clock, ChevronRight, CheckCircle, Share2 } from 'lucide-react';
import api from '../../api';
import { toast } from 'sonner';

const SEVERITY_STYLES = {
  critical: { bg: 'bg-red-500/10', border: 'border-red-500/30', dot: 'bg-red-500', text: 'text-red-400' },
  high: { bg: 'bg-orange-500/10', border: 'border-orange-500/30', dot: 'bg-orange-500', text: 'text-orange-400' },
  medium: { bg: 'bg-amber-500/10', border: 'border-amber-500/30', dot: 'bg-amber-500', text: 'text-amber-400' },
  low: { bg: 'bg-slate-500/10', border: 'border-slate-500/30', dot: 'bg-slate-400', text: 'text-slate-400' },
  tracking: { bg: 'bg-teal-500/10', border: 'border-teal-500/30', dot: 'bg-teal-500', text: 'text-teal-400' },
  safe: { bg: 'bg-emerald-500/10', border: 'border-emerald-500/30', dot: 'bg-emerald-500', text: 'text-emerald-400' },
  info: { bg: 'bg-blue-500/10', border: 'border-blue-500/30', dot: 'bg-blue-500', text: 'text-blue-400' },
  warning: { bg: 'bg-amber-500/10', border: 'border-amber-500/30', dot: 'bg-amber-500', text: 'text-amber-400' },
};

const TYPE_ICONS = {
  sos: Radio,
  fall: AlertTriangle,
  geofence: MapPin,
  live_tracking: Share2,
  tracking_stop: MapPin,
  tracking_deviation: AlertTriangle,
  safe_zone_exit: MapPin,
  unknown_area_entry: AlertTriangle,
  safe_zone_arrival: MapPin,
  danger_zone_entry: AlertTriangle,
  default: AlertTriangle,
};

const IncidentItem = ({ incident, onSelect, onAcknowledge }) => {
  const isTracking = incident.incident_type === 'live_tracking';
  const isTrailEvent = incident.incident_type === 'tracking_stop' || incident.incident_type === 'tracking_deviation';
  const isZoneEvent = ['safe_zone_exit', 'unknown_area_entry', 'safe_zone_arrival', 'danger_zone_entry'].includes(incident.incident_type);
  const isSpecial = isTracking || isTrailEvent || isZoneEvent;

  const severityKey = isTracking ? 'tracking'
    : incident.incident_type === 'tracking_stop' ? 'tracking'
    : incident.incident_type === 'tracking_deviation' ? 'medium'
    : incident.incident_type === 'safe_zone_arrival' ? 'safe'
    : incident.incident_type === 'safe_zone_exit' ? 'info'
    : incident.incident_type === 'unknown_area_entry' ? 'warning'
    : incident.incident_type === 'danger_zone_entry' ? 'critical'
    : incident.severity;
  const s = SEVERITY_STYLES[severityKey] || SEVERITY_STYLES.low;
  const Icon = TYPE_ICONS[incident.incident_type] || TYPE_ICONS.default;
  const time = incident.created_at ? new Date(incident.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '';
  const isOpen = incident.status === 'open' || incident.status === 'active';

  const handleAck = async (e) => {
    e.stopPropagation();
    if (isSpecial) return;
    try {
      await api.patch(`/incidents/${incident.id}/acknowledge?channel=dashboard`);
      toast.success('Incident acknowledged');
      onAcknowledge?.(incident.id);
    } catch {
      toast.error('Failed to acknowledge');
    }
  };

  const typeLabel = isTracking ? 'Live Tracking'
    : incident.incident_type === 'tracking_stop' ? 'Stop Detected'
    : incident.incident_type === 'tracking_deviation' ? 'Route Deviation'
    : incident.incident_type === 'safe_zone_exit' ? 'Zone Exit'
    : incident.incident_type === 'safe_zone_arrival' ? 'Zone Arrival'
    : incident.incident_type === 'unknown_area_entry' ? 'Unknown Area'
    : incident.incident_type === 'danger_zone_entry' ? 'Danger Zone'
    : (incident.incident_type?.replace('_', ' ') || 'Alert');

  const description = isTracking
    ? `${incident.senior_name || incident.user_name || 'Unknown'} \u2014 Live tracking link shared`
    : (isTrailEvent || isZoneEvent)
    ? `${incident.senior_name || incident.user_name || 'Unknown'} \u2014 ${incident.detail || typeLabel}`
    : (incident.senior_name || incident.device_identifier || 'Unknown');

  return (
    <div
      onClick={() => !isSpecial && onSelect?.(incident)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && !isSpecial && onSelect?.(incident)}
      className={`w-full text-left p-3 rounded-lg border ${s.bg} ${s.border} hover:brightness-125 transition-all group cursor-pointer`}
      data-testid={isSpecial ? 'cc-tracking-event' : 'cc-incident-item'}
    >
      <div className="flex items-start gap-2.5">
        <div className={`w-7 h-7 rounded-md ${s.bg} flex items-center justify-center shrink-0 mt-0.5`}>
          <Icon className={`w-3.5 h-3.5 ${s.text}`} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between gap-2">
            <span className={`text-xs font-semibold uppercase tracking-wider ${s.text}`}>{typeLabel}</span>
            <span className="text-[10px] text-slate-500 flex items-center gap-1"><Clock className="w-2.5 h-2.5" />{time}</span>
          </div>
          <p className="text-sm text-slate-300 truncate mt-0.5">{description}</p>
          <div className="flex items-center justify-between mt-1.5">
            {isSpecial ? (
              <span className={`text-[10px] px-1.5 py-0.5 rounded ${s.bg} ${s.text} border ${s.border} flex items-center gap-1`}>
                <span className={`w-1.5 h-1.5 rounded-full ${incident.status === 'active' ? s.dot + ' animate-pulse' : 'bg-slate-500'}`} />
                {isTracking ? (incident.status === 'active' ? 'LIVE' : 'ENDED')
                  : incident.incident_type === 'tracking_deviation' ? 'WARNING'
                  : incident.incident_type === 'danger_zone_entry' ? 'CRITICAL'
                  : incident.incident_type === 'unknown_area_entry' ? 'WARNING'
                  : incident.incident_type === 'safe_zone_arrival' ? 'SAFE'
                  : incident.incident_type === 'safe_zone_exit' ? 'INFO'
                  : 'NOTICE'}
              </span>
            ) : (
              <span className={`text-[10px] px-1.5 py-0.5 rounded ${s.bg} ${s.text} border ${s.border}`}>{incident.severity}</span>
            )}
            {!isSpecial && isOpen ? (
              <button
                onClick={handleAck}
                className="flex items-center gap-1 px-2 py-1 rounded-md bg-teal-500/15 border border-teal-500/30 text-teal-400 text-[10px] font-semibold hover:bg-teal-500/25 transition-colors"
                data-testid="acknowledge-incident-btn"
              >
                <CheckCircle className="w-3 h-3" /> Acknowledge
              </button>
            ) : !isSpecial ? (
              <span className="text-[10px] text-slate-500 flex items-center gap-1">
                <CheckCircle className="w-3 h-3" /> {incident.status}
              </span>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
};

export const IncidentFeed = ({ incidents = [], sseEvents = [], onSelectIncident, onRefresh }) => {
  const allEvents = [
    ...sseEvents.map(e => ({
      id: e.sos_id || e.id || `sse-${Date.now()}`,
      incident_type: e.type || 'sos',
      severity: 'critical',
      senior_name: e.user_name || e.user_id,
      created_at: e.timestamp || new Date().toISOString(),
      status: 'active',
      ...e,
    })),
    ...incidents,
  ].sort((a, b) => new Date(b.created_at) - new Date(a.created_at)).slice(0, 30);

  return (
    <div className="h-full rounded-xl bg-slate-900 border border-slate-800 flex flex-col" data-testid="cc-incident-feed">
      <div className="px-4 py-3 border-b border-slate-700/50 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-2">
          <Radio className="w-4 h-4 text-red-400" />
          <h3 className="text-sm font-semibold text-white">Incident Feed</h3>
        </div>
        <span className="text-[10px] bg-slate-700/50 text-slate-400 px-2 py-0.5 rounded-full">{allEvents.length}</span>
      </div>
      <div className="flex-1 overflow-y-auto p-3 space-y-2 scrollbar-thin scrollbar-thumb-slate-700">
        {allEvents.length === 0 ? (
          <div className="text-center py-8">
            <p className="text-xs text-slate-500">No active incidents</p>
            <p className="text-[10px] text-slate-600 mt-1">System monitoring active</p>
          </div>
        ) : (
          allEvents.map((inc, i) => (
            <IncidentItem key={inc.id || i} incident={inc} onSelect={onSelectIncident} onAcknowledge={onRefresh} />
          ))
        )}
      </div>
    </div>
  );
};
