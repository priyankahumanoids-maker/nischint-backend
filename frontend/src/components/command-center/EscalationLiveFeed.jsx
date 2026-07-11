import React, { useState, useEffect, useRef } from 'react';
import { Phone, PhoneOff, PhoneMissed, MessageSquare, CheckCircle, AlertTriangle, Clock, XCircle } from 'lucide-react';

const STATUS_CONFIG = {
  started: { icon: AlertTriangle, color: 'text-orange-400', bg: 'bg-orange-500/10', label: 'Escalation Started' },
  calling: { icon: Phone, color: 'text-yellow-400', bg: 'bg-yellow-500/10', label: 'Calling' },
  no_answer: { icon: PhoneMissed, color: 'text-red-400', bg: 'bg-red-500/10', label: 'No Answer' },
  voicemail: { icon: PhoneOff, color: 'text-orange-400', bg: 'bg-orange-500/10', label: 'Voicemail' },
  answered: { icon: CheckCircle, color: 'text-emerald-400', bg: 'bg-emerald-500/10', label: 'Answered' },
  failed: { icon: XCircle, color: 'text-red-500', bg: 'bg-red-500/10', label: 'Failed' },
  sms_blast: { icon: MessageSquare, color: 'text-orange-400', bg: 'bg-orange-500/10', label: 'SMS Blast' },
  exhausted: { icon: AlertTriangle, color: 'text-red-500', bg: 'bg-red-500/10', label: 'All Exhausted' },
};

export function EscalationLiveFeed({ events = [] }) {
  if (events.length === 0) {
    return (
      <div className="rounded-xl bg-slate-900 border border-slate-800 p-4" data-testid="escalation-live-feed">
        <div className="flex items-center gap-2 mb-3">
          <Phone className="w-4 h-4 text-amber-400" />
          <h3 className="text-xs font-semibold text-white">Escalation Live Feed</h3>
        </div>
        <p className="text-[10px] text-slate-500 text-center py-4">No active escalations</p>
      </div>
    );
  }

  return (
    <div className="rounded-xl bg-slate-900 border border-slate-800 flex flex-col" data-testid="escalation-live-feed">
      <div className="px-3 py-2 border-b border-slate-700/50 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-1.5">
          <Phone className="w-3.5 h-3.5 text-amber-400" />
          <h3 className="text-[11px] font-semibold text-white">Escalation Live Feed</h3>
        </div>
        <span className="text-[8px] px-1.5 py-0.5 rounded bg-red-500/20 text-red-400 font-semibold">
          {events.length} EVENTS
        </span>
      </div>

      <div className="flex-1 overflow-y-auto max-h-[280px]">
        <table className="w-full text-[10px]">
          <thead>
            <tr className="border-b border-slate-800">
              <th className="px-2 py-1.5 text-left text-slate-500 font-medium">Child</th>
              <th className="px-2 py-1.5 text-left text-slate-500 font-medium">Guardian</th>
              <th className="px-2 py-1.5 text-left text-slate-500 font-medium">Status</th>
              <th className="px-2 py-1.5 text-left text-slate-500 font-medium">Step</th>
              <th className="px-2 py-1.5 text-right text-slate-500 font-medium">Time</th>
            </tr>
          </thead>
          <tbody>
            {events.map((evt, i) => {
              const config = STATUS_CONFIG[evt.status] || STATUS_CONFIG.started;
              const Icon = config.icon;
              const isActive = evt.status === 'calling';

              return (
                <tr
                  key={`${evt.event_id}-${evt.timestamp}-${i}`}
                  className={`border-b border-slate-800/50 ${isActive ? 'animate-pulse' : ''} ${config.bg}`}
                  data-testid={`escalation-event-${i}`}
                >
                  <td className="px-2 py-1.5 text-slate-300 font-medium">
                    {evt.child_name}
                  </td>
                  <td className="px-2 py-1.5">
                    <span className="text-slate-300">
                      {evt.current_guardian?.name || '-'}
                    </span>
                  </td>
                  <td className="px-2 py-1.5">
                    <div className="flex items-center gap-1">
                      <Icon className={`w-3 h-3 ${config.color}`} />
                      <span className={`${config.color} font-medium`}>
                        {config.label}
                      </span>
                    </div>
                  </td>
                  <td className="px-2 py-1.5 text-slate-400">
                    {evt.sequence > 0 ? `${evt.sequence}/${evt.total_guardians}` : '-'}
                  </td>
                  <td className="px-2 py-1.5 text-right text-slate-500">
                    {evt.timestamp ? new Date(evt.timestamp).toLocaleTimeString() : '-'}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Resolution banner */}
      {events.length > 0 && events[0].status === 'answered' && events[0].resolved_by && (
        <div className="px-3 py-2 border-t border-emerald-500/30 bg-emerald-500/10 flex items-center gap-2">
          <CheckCircle className="w-3.5 h-3.5 text-emerald-400" />
          <span className="text-[10px] text-emerald-400 font-semibold">
            Resolved by: {events[0].resolved_by}
          </span>
          <span className="text-[9px] text-emerald-500/60 ml-auto">
            {new Date(events[0].timestamp).toLocaleTimeString()}
          </span>
        </div>
      )}

      {events.length > 0 && events[0].status === 'exhausted' && (
        <div className="px-3 py-2 border-t border-red-500/30 bg-red-500/10 flex items-center gap-2">
          <AlertTriangle className="w-3.5 h-3.5 text-red-400" />
          <span className="text-[10px] text-red-400 font-semibold">
            ALL CONTACTS EXHAUSTED — SMS blast sent
          </span>
        </div>
      )}
    </div>
  );
}
