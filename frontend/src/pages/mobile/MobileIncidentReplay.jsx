import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ArrowLeft, AlertTriangle, Shield, MapPin, Clock, ChevronRight,
  Loader2, Activity, FileText, Zap, Eye, RefreshCw,
} from 'lucide-react';
import api from '../../api';

const SEVERITY_STYLES = {
  critical: { bg: 'bg-red-500/10', border: 'border-red-500/40', text: 'text-red-400', dot: 'bg-red-400' },
  high: { bg: 'bg-orange-500/10', border: 'border-orange-500/40', text: 'text-orange-400', dot: 'bg-orange-400' },
  moderate: { bg: 'bg-amber-500/10', border: 'border-amber-500/40', text: 'text-amber-400', dot: 'bg-amber-400' },
  medium: { bg: 'bg-amber-500/10', border: 'border-amber-500/40', text: 'text-amber-400', dot: 'bg-amber-400' },
  low: { bg: 'bg-emerald-500/10', border: 'border-emerald-500/40', text: 'text-emerald-400', dot: 'bg-emerald-400' },
  info: { bg: 'bg-blue-500/10', border: 'border-blue-500/40', text: 'text-blue-400', dot: 'bg-blue-400' },
};

function getSev(sev) { return SEVERITY_STYLES[sev] || SEVERITY_STYLES.info; }

function formatTime(iso) {
  if (!iso) return '';
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function formatDate(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  const today = new Date();
  if (d.toDateString() === today.toDateString()) return 'Today';
  const yesterday = new Date(today); yesterday.setDate(today.getDate() - 1);
  if (d.toDateString() === yesterday.toDateString()) return 'Yesterday';
  return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
}

function formatDuration(seconds) {
  if (!seconds) return 'N/A';
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

export default function MobileIncidentReplay() {
  const navigate = useNavigate();
  const [incidents, setIncidents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState(null);
  const [replay, setReplay] = useState(null);
  const [replayLoading, setReplayLoading] = useState(false);

  useEffect(() => {
    api.get('/guardian/incidents?limit=50').then(res => {
      setIncidents(res.data?.incidents || []);
    }).catch(() => {}).finally(() => setLoading(false));
  }, []);

  const loadReplay = useCallback(async (id) => {
    setSelectedId(id);
    setReplayLoading(true);
    try {
      const res = await api.get(`/guardian/incidents/${id}/replay`);
      setReplay(res.data);
    } catch {
      setReplay(null);
    } finally {
      setReplayLoading(false);
    }
  }, []);

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center" data-testid="incidents-loading">
        <Loader2 className="w-8 h-8 text-teal-400 animate-spin" />
      </div>
    );
  }

  // Replay detail view
  if (selectedId && replay) {
    return <ReplayView replay={replay} onBack={() => { setSelectedId(null); setReplay(null); }} />;
  }

  return (
    <div className="px-4 py-3 pb-24" data-testid="mobile-incidents">
      {/* Header */}
      <div className="flex items-center gap-3 mb-5">
        <button onClick={() => navigate(-1)} className="p-1.5 rounded-xl bg-slate-800/60" data-testid="incidents-back-btn">
          <ArrowLeft className="w-5 h-5 text-slate-400" />
        </button>
        <div>
          <h1 className="text-lg font-semibold">Incident Replay</h1>
          <p className="text-[10px] text-slate-500">{incidents.length} incidents recorded</p>
        </div>
      </div>

      {incidents.length === 0 ? (
        <div className="text-center py-16" data-testid="no-incidents">
          <Shield className="w-10 h-10 text-slate-700 mx-auto mb-3" />
          <p className="text-slate-500 text-sm">No incidents recorded</p>
          <p className="text-slate-600 text-xs mt-1">Safety events and alerts will appear here</p>
        </div>
      ) : (
        <div className="space-y-2">
          {/* Group by date */}
          {groupByDate(incidents).map(([date, items]) => (
            <div key={date}>
              <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-1.5 px-1">{date}</p>
              <div className="space-y-1.5">
                {items.map(inc => {
                  const sev = getSev(inc.severity);
                  return (
                    <button
                      key={inc.id}
                      onClick={() => inc.type === 'alert' ? loadReplay(inc.id) : null}
                      className={`w-full text-left p-3 rounded-xl ${sev.bg} border ${sev.border} transition-all active:scale-[0.98]`}
                      data-testid={`incident-${inc.id}`}
                    >
                      <div className="flex items-start gap-3">
                        <div className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 ${
                          inc.type === 'sos' ? 'bg-red-500/20' : 'bg-slate-800/50'
                        }`}>
                          {inc.type === 'sos' ? (
                            <Shield className="w-4 h-4 text-red-400" />
                          ) : (
                            <AlertTriangle className={`w-4 h-4 ${sev.text}`} />
                          )}
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <p className={`text-sm font-medium ${sev.text}`}>
                              {inc.alert_type?.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()) || 'Alert'}
                            </p>
                            <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded ${sev.bg} ${sev.text} border ${sev.border}`}>
                              {inc.severity?.toUpperCase()}
                            </span>
                          </div>
                          <p className="text-xs text-slate-400 mt-0.5 line-clamp-1">{inc.message}</p>
                          <div className="flex items-center gap-3 mt-1.5">
                            <span className="text-[10px] text-slate-500 flex items-center gap-1">
                              <Clock className="w-3 h-3" /> {formatTime(inc.created_at)}
                            </span>
                            {inc.risk_score > 0 && (
                              <span className="text-[10px] text-slate-500 flex items-center gap-1">
                                <Activity className="w-3 h-3" /> Risk: {inc.risk_score}
                              </span>
                            )}
                          </div>
                        </div>
                        {inc.type === 'alert' && (
                          <ChevronRight className="w-4 h-4 text-slate-600 shrink-0 mt-1" />
                        )}
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function groupByDate(incidents) {
  const groups = {};
  for (const inc of incidents) {
    const d = formatDate(inc.created_at);
    if (!groups[d]) groups[d] = [];
    groups[d].push(inc);
  }
  return Object.entries(groups);
}

function ReplayView({ replay, onBack }) {
  const [activeEvent, setActiveEvent] = useState(null);
  const timeline = replay?.timeline || [];
  const ai = replay?.ai_analysis || {};

  return (
    <div className="px-4 py-3 pb-24" data-testid="incident-replay-view">
      {/* Header */}
      <div className="flex items-center gap-3 mb-4">
        <button onClick={onBack} className="p-1.5 rounded-xl bg-slate-800/60" data-testid="replay-back-btn">
          <ArrowLeft className="w-5 h-5 text-slate-400" />
        </button>
        <div className="flex-1">
          <h1 className="text-base font-semibold">
            {replay.incident_type?.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}
          </h1>
          <p className="text-[10px] text-slate-500">{formatTime(replay.incident_time)} · {formatDate(replay.incident_time)}</p>
        </div>
        <span className={`text-xs font-bold px-2 py-1 rounded-lg ${getSev(replay.severity).bg} ${getSev(replay.severity).text} border ${getSev(replay.severity).border}`}>
          {replay.severity?.toUpperCase()}
        </span>
      </div>

      {/* Incident Summary Card */}
      <div className="bg-slate-900/80 border border-slate-800/60 rounded-2xl p-4 mb-4" data-testid="incident-summary-card">
        <p className="text-sm text-slate-300">{replay.message}</p>
        <div className="flex items-center gap-4 mt-2.5">
          <div className="flex items-center gap-1.5">
            <MapPin className="w-3.5 h-3.5 text-slate-500" />
            <span className="text-[10px] text-slate-400">{replay.session?.total_distance_m || 0}m traveled</span>
          </div>
          <div className="flex items-center gap-1.5">
            <Clock className="w-3.5 h-3.5 text-slate-500" />
            <span className="text-[10px] text-slate-400">{replay.stats?.total_alerts || 0} alerts</span>
          </div>
          {replay.session?.destination?.name && (
            <div className="flex items-center gap-1.5">
              <Zap className="w-3.5 h-3.5 text-slate-500" />
              <span className="text-[10px] text-slate-400">{replay.session.destination.name}</span>
            </div>
          )}
        </div>
      </div>

      {/* Timeline */}
      <div className="mb-4" data-testid="incident-timeline">
        <div className="flex items-center gap-2 mb-3">
          <Eye className="w-4 h-4 text-teal-400" />
          <h2 className="text-sm font-semibold">Event Timeline</h2>
        </div>

        <div className="relative pl-6">
          {/* Timeline line */}
          <div className="absolute left-[9px] top-2 bottom-2 w-px bg-slate-700/50" />

          <div className="space-y-3">
            {timeline.map((ev, i) => {
              const sev = getSev(ev.severity);
              const isIncident = ev.is_current;
              return (
                <button
                  key={i}
                  onClick={() => setActiveEvent(activeEvent === i ? null : i)}
                  className={`w-full text-left relative transition-all ${isIncident ? 'scale-[1.02]' : ''}`}
                  data-testid={`timeline-event-${i}`}
                >
                  {/* Dot */}
                  <div className={`absolute -left-6 top-1.5 w-[18px] h-[18px] rounded-full border-2 ${
                    isIncident ? 'border-red-400 bg-red-500/30' : `border-slate-700 ${sev.dot.replace('bg-', 'bg-')}/30`
                  } flex items-center justify-center`}>
                    <div className={`w-2 h-2 rounded-full ${isIncident ? 'bg-red-400' : sev.dot}`} />
                  </div>

                  <div className={`p-2.5 rounded-xl ${isIncident ? 'bg-red-500/10 border border-red-500/30' : 'bg-slate-900/50 border border-slate-800/40'}`}>
                    <div className="flex items-center justify-between">
                      <span className={`text-xs font-medium ${isIncident ? 'text-red-400' : 'text-slate-300'}`}>
                        {ev.type?.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}
                      </span>
                      <span className="text-[10px] text-slate-500">{formatTime(ev.time)}</span>
                    </div>
                    <p className="text-[11px] text-slate-400 mt-0.5">{ev.message}</p>

                    {/* Expanded details */}
                    {activeEvent === i && ev.recommendation && (
                      <div className="mt-2 pt-2 border-t border-slate-800/40">
                        <p className="text-[10px] text-slate-500">{ev.recommendation}</p>
                        {ev.risk_score > 0 && (
                          <span className="text-[10px] text-slate-600 mt-1 block">Risk: {ev.risk_score}/10</span>
                        )}
                      </div>
                    )}
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      </div>

      {/* AI Analysis Panel */}
      <div className="bg-gradient-to-br from-slate-900/90 to-slate-800/50 border border-slate-700/50 rounded-2xl p-4 mb-4" data-testid="ai-analysis-panel">
        <div className="flex items-center gap-2 mb-3">
          <div className="w-7 h-7 rounded-lg bg-violet-500/15 flex items-center justify-center">
            <FileText className="w-3.5 h-3.5 text-violet-400" />
          </div>
          <h2 className="text-sm font-semibold">AI Analysis</h2>
        </div>

        <div className="space-y-3">
          {/* Root Cause */}
          <div>
            <p className="text-[10px] text-slate-500 uppercase mb-0.5">Root Cause</p>
            <p className="text-xs text-slate-300">{ai.root_cause || 'Analyzing...'}</p>
          </div>

          {/* Stats Row */}
          <div className="grid grid-cols-3 gap-2">
            <div className="text-center p-2 rounded-lg bg-slate-800/50">
              <p className={`text-lg font-bold ${ai.risk_score_at_incident > 5 ? 'text-red-400' : 'text-amber-400'}`}>
                {ai.risk_score_at_incident || 0}
              </p>
              <p className="text-[9px] text-slate-500">Risk Score</p>
            </div>
            <div className="text-center p-2 rounded-lg bg-slate-800/50">
              <p className="text-lg font-bold text-blue-400">{formatDuration(ai.response_time_seconds)}</p>
              <p className="text-[9px] text-slate-500">Response</p>
            </div>
            <div className="text-center p-2 rounded-lg bg-slate-800/50">
              <p className={`text-lg font-bold ${ai.preventable ? 'text-emerald-400' : 'text-red-400'}`}>
                {ai.preventable ? 'YES' : 'NO'}
              </p>
              <p className="text-[9px] text-slate-500">Preventable</p>
            </div>
          </div>

          {/* Contributing Factors */}
          {ai.contributing_factors?.length > 0 && (
            <div>
              <p className="text-[10px] text-slate-500 uppercase mb-1">Contributing Factors</p>
              <div className="flex flex-wrap gap-1">
                {ai.contributing_factors.map((f, i) => (
                  <span key={i} className="text-[10px] px-2 py-0.5 rounded-full bg-violet-500/10 text-violet-400 border border-violet-500/20">
                    {f}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Recommendation */}
          <div className="p-2.5 rounded-xl bg-teal-500/5 border border-teal-500/20">
            <p className="text-[10px] text-teal-400 font-medium flex items-center gap-1">
              <RefreshCw className="w-3 h-3" /> Recommendation
            </p>
            <p className="text-xs text-slate-300 mt-0.5">{ai.recommendation}</p>
          </div>
        </div>
      </div>
    </div>
  );
}
