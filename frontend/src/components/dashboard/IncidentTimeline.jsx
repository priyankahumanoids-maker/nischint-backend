import React, { useState, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../ui/card';
import {
  AlertTriangle, Bell, CheckCircle, XCircle, Activity,
  Loader2, Clock, Shield, ArrowRight,
} from 'lucide-react';
import api from '../../api';

const EVENT_CONFIG = {
  incident_created: { icon: AlertTriangle, color: 'text-red-500', bg: 'bg-red-100', border: 'border-red-400', label: 'Created' },
  escalation_l1: { icon: Bell, color: 'text-orange-500', bg: 'bg-orange-100', border: 'border-orange-400', label: 'L1 Escalation' },
  escalation_l2: { icon: Bell, color: 'text-red-500', bg: 'bg-red-100', border: 'border-red-500', label: 'L2 Escalation' },
  escalation_l3: { icon: Shield, color: 'text-red-700', bg: 'bg-red-200', border: 'border-red-600', label: 'L3 Operator' },
  acknowledged: { icon: CheckCircle, color: 'text-blue-500', bg: 'bg-blue-100', border: 'border-blue-400', label: 'Acknowledged' },
  resolve: { icon: CheckCircle, color: 'text-green-500', bg: 'bg-green-100', border: 'border-green-400', label: 'Resolved' },
  false_alarm: { icon: XCircle, color: 'text-slate-500', bg: 'bg-slate-100', border: 'border-slate-400', label: 'False Alarm' },
  device_offline_detected: { icon: Activity, color: 'text-amber-500', bg: 'bg-amber-100', border: 'border-amber-400', label: 'Device Offline' },
  test_auto_resolved: { icon: CheckCircle, color: 'text-slate-400', bg: 'bg-slate-50', border: 'border-slate-300', label: 'Auto-Resolved' },
};

const DEFAULT_EVENT = { icon: Activity, color: 'text-slate-400', bg: 'bg-slate-50', border: 'border-slate-300', label: 'Event' };

function formatEventTime(dateStr) {
  if (!dateStr) return '';
  const d = new Date(dateStr);
  return d.toLocaleString(undefined, {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit',
  });
}

function timeBetween(from, to) {
  if (!from || !to) return null;
  const diff = (new Date(to) - new Date(from)) / 1000;
  if (diff < 0) return null;
  if (diff < 60) return `${Math.round(diff)}s`;
  if (diff < 3600) return `${Math.round(diff / 60)}m`;
  return `${Math.floor(diff / 3600)}h ${Math.round((diff % 3600) / 60)}m`;
}

export default function IncidentTimeline({ incidentId, onClose }) {
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!incidentId) return;
    setLoading(true);
    api.get(`/incidents/${incidentId}/events`)
      .then(res => {
        const sorted = [...(res.data || [])].sort(
          (a, b) => new Date(a.created_at) - new Date(b.created_at)
        );
        setEvents(sorted);
      })
      .catch(() => setEvents([]))
      .finally(() => setLoading(false));
  }, [incidentId]);

  if (!incidentId) return null;

  return (
    <Card className="border-slate-200" data-testid="incident-timeline-card">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2 text-base">
            <Clock className="w-4 h-4 text-slate-500" />
            Incident Timeline
          </CardTitle>
          {onClose && (
            <button onClick={onClose} className="text-xs text-slate-400 hover:text-slate-600" data-testid="timeline-close-btn">
              Close
            </button>
          )}
        </div>
      </CardHeader>
      <CardContent>
        {loading ? (
          <div className="flex items-center gap-2 py-4 text-slate-400" data-testid="timeline-loading">
            <Loader2 className="w-4 h-4 animate-spin" /> Loading timeline...
          </div>
        ) : events.length === 0 ? (
          <p className="text-sm text-slate-400 py-4" data-testid="timeline-empty">No events recorded yet</p>
        ) : (
          <div className="relative pl-6" data-testid="timeline-events">
            {/* Vertical line */}
            <div className="absolute left-[11px] top-2 bottom-2 w-0.5 bg-slate-200" />

            {events.map((event, idx) => {
              const config = EVENT_CONFIG[event.event_type] || DEFAULT_EVENT;
              const Icon = config.icon;
              const gap = idx > 0 ? timeBetween(events[idx - 1].created_at, event.created_at) : null;

              return (
                <div key={event.id} className="relative mb-4 last:mb-0" data-testid={`timeline-event-${idx}`}>
                  {/* Gap indicator */}
                  {gap && (
                    <div className="absolute -left-[13px] -top-3 flex items-center gap-1 text-[9px] text-slate-400">
                      <ArrowRight className="w-2.5 h-2.5" />
                      <span>+{gap}</span>
                    </div>
                  )}
                  {/* Dot */}
                  <div className={`absolute -left-[15px] top-1 w-5 h-5 rounded-full ${config.bg} flex items-center justify-center ring-2 ring-white`}>
                    <Icon className={`w-3 h-3 ${config.color}`} />
                  </div>
                  {/* Content */}
                  <div className={`border-l-2 ${config.border} pl-3 py-1`}>
                    <div className="flex items-center gap-2">
                      <span className={`text-sm font-semibold ${config.color}`}>{config.label}</span>
                      {event.event_channel && (
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500">
                          via {event.event_channel}
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-slate-400 mt-0.5">{formatEventTime(event.created_at)}</p>
                    {event.metadata && Object.keys(event.metadata).length > 0 && (
                      <div className="mt-1 text-[10px] text-slate-400">
                        {event.metadata.acknowledged_by_name && (
                          <span>By: {event.metadata.acknowledged_by_name}</span>
                        )}
                        {event.metadata.acknowledged_via && (
                          <span className="ml-2">Channel: {event.metadata.acknowledged_via}</span>
                        )}
                        {event.metadata.guardian_email && (
                          <span>Notified: {event.metadata.guardian_email}</span>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
