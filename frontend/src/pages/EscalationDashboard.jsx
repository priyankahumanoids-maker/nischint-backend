import React, { useState, useEffect, useCallback } from 'react';
import { Card, CardContent } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { operatorApi } from '../api';
import { toast } from 'sonner';
import {
  Shield, Clock, AlertTriangle, CheckCircle, Loader2, RefreshCw,
  ChevronRight, Users, Headphones, Timer, ArrowUpRight, Brain,
  TrendingDown, TrendingUp, BarChart3, Minus,
} from 'lucide-react';

export default function EscalationDashboard() {
  const [config, setConfig] = useState(null);
  const [pending, setPending] = useState(null);
  const [history, setHistory] = useState(null);
  const [loading, setLoading] = useState(true);
  const [acknowledging, setAcknowledging] = useState({});
  const [smartRec, setSmartRec] = useState({}); // { incidentId: { loading, data } }
  const [guardianProfiles, setGuardianProfiles] = useState({}); // { guardianId: { loading, data } }

  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      const [cfgRes, pendRes, histRes] = await Promise.all([
        operatorApi.getEscalationConfig(),
        operatorApi.getEscalationPending(),
        operatorApi.getEscalationHistory(15),
      ]);
      setConfig(cfgRes.data);
      setPending(pendRes.data);
      setHistory(histRes.data);
    } catch {
      toast.error('Failed to load escalation data');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  // Auto-refresh pending every 30s
  useEffect(() => {
    const iv = setInterval(async () => {
      try {
        const res = await operatorApi.getEscalationPending();
        setPending(res.data);
      } catch {}
    }, 30000);
    return () => clearInterval(iv);
  }, []);

  const handleAcknowledge = async (incidentId) => {
    setAcknowledging(prev => ({ ...prev, [incidentId]: true }));
    try {
      await operatorApi.acknowledgeIncident(incidentId);
      toast.success('Incident acknowledged — escalation stopped');
      fetchAll();
    } catch {
      toast.error('Failed to acknowledge incident');
    } finally {
      setAcknowledging(prev => ({ ...prev, [incidentId]: false }));
    }
  };

  const handleSmartRec = async (incidentId) => {
    setSmartRec(prev => ({ ...prev, [incidentId]: { loading: true, data: null } }));
    try {
      const res = await operatorApi.getSmartRecommendation(incidentId);
      setSmartRec(prev => ({ ...prev, [incidentId]: { loading: false, data: res.data } }));
    } catch {
      setSmartRec(prev => ({ ...prev, [incidentId]: { loading: false, data: null } }));
      toast.error('Failed to get AI recommendation');
    }
  };

  const handleGuardianProfile = async (guardianId, guardianEmail) => {
    if (guardianProfiles[guardianId]?.data) return; // already loaded
    setGuardianProfiles(prev => ({ ...prev, [guardianId]: { loading: true, data: null, email: guardianEmail } }));
    try {
      const res = await operatorApi.getSmartGuardianProfile(guardianId);
      setGuardianProfiles(prev => ({ ...prev, [guardianId]: { loading: false, data: res.data, email: guardianEmail } }));
    } catch {
      setGuardianProfiles(prev => ({ ...prev, [guardianId]: { loading: false, data: null, email: guardianEmail } }));
    }
  };

  const formatTime = (seconds) => {
    if (seconds === null || seconds === undefined) return '—';
    if (seconds <= 0) return 'OVERDUE';
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return m > 0 ? `${m}m ${s}s` : `${s}s`;
  };

  const severityColor = (sev) => {
    const map = { critical: 'bg-red-100 text-red-700', high: 'bg-orange-100 text-orange-700', medium: 'bg-yellow-100 text-yellow-700', low: 'bg-slate-100 text-slate-600' };
    return map[sev] || 'bg-slate-100 text-slate-600';
  };

  const levelIcon = (level) => {
    if (level === 1) return <Shield className="w-3.5 h-3.5 text-blue-500" />;
    if (level === 2) return <Users className="w-3.5 h-3.5 text-amber-500" />;
    if (level === 3) return <Headphones className="w-3.5 h-3.5 text-red-500" />;
    return <Clock className="w-3.5 h-3.5 text-slate-400" />;
  };

  if (loading) return (
    <div className="flex items-center justify-center py-12">
      <Loader2 className="w-6 h-6 animate-spin text-slate-400" />
    </div>
  );

  return (
    <div className="space-y-6" data-testid="escalation-dashboard">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold text-slate-800">Guardian AI Decision Engine</h2>
        <Button variant="outline" size="sm" onClick={fetchAll} data-testid="refresh-escalation">
          <RefreshCw className="w-4 h-4 mr-2" /> Refresh
        </Button>
      </div>

      {/* Escalation Config */}
      {config && (
        <Card data-testid="escalation-config-card">
          <CardContent className="p-5">
            <h3 className="text-lg font-semibold text-slate-800 mb-3 flex items-center gap-2">
              <Timer className="w-5 h-5 text-blue-500" />
              Escalation Rules
            </h3>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              {Object.entries(config.levels).map(([key, level]) => {
                const timerKey = key.replace('level', 'level') + '_minutes';
                const minutes = config.timers[timerKey];
                return (
                  <div key={key} className="p-3 rounded-lg border border-slate-100 bg-slate-50/50" data-testid={`escalation-${key}`}>
                    <div className="flex items-center gap-2 mb-1">
                      {levelIcon(parseInt(key.replace('level', '')))}
                      <span className="font-semibold text-slate-700 text-sm">{key.replace('level', 'Level ')}</span>
                      <Badge className="ml-auto bg-blue-50 text-blue-700 text-xs">{minutes} min</Badge>
                    </div>
                    <p className="text-xs text-slate-500">{level.target}</p>
                    <div className="flex gap-1 mt-1.5 flex-wrap">
                      {level.channels.map(ch => (
                        <span key={ch} className="text-[10px] px-1.5 py-0.5 bg-white border border-slate-200 rounded text-slate-500">{ch}</span>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
            <p className="text-xs text-slate-400 mt-3 flex items-center gap-1">
              <CheckCircle className="w-3 h-3 text-green-500" />
              Acknowledging an incident stops further escalation. Check interval: every {config.check_interval_seconds}s.
            </p>
          </CardContent>
        </Card>
      )}

      {/* Pending Escalations */}
      {pending && (
        <Card data-testid="pending-escalations-card">
          <CardContent className="p-5">
            <h3 className="text-lg font-semibold text-slate-800 mb-3 flex items-center gap-2">
              <AlertTriangle className="w-5 h-5 text-amber-500" />
              Pending Escalations
              {pending.count > 0 && (
                <Badge className="bg-red-100 text-red-700 ml-2" data-testid="pending-count">{pending.count}</Badge>
              )}
            </h3>
            {pending.count === 0 ? (
              <div className="text-center py-6" data-testid="no-pending">
                <CheckCircle className="w-8 h-8 mx-auto text-green-400 mb-2" />
                <p className="text-sm text-slate-500">All clear — no pending escalations</p>
              </div>
            ) : (
              <div className="space-y-2" data-testid="pending-list">
                {pending.pending.map(p => (
                  <div key={p.incident_id} className={`flex items-center gap-3 p-3 rounded-lg border ${
                    p.overdue ? 'border-red-200 bg-red-50' :
                    p.time_remaining_seconds < 60 ? 'border-amber-200 bg-amber-50' :
                    'border-slate-100 bg-white'
                  }`} data-testid={`pending-${p.incident_id}`}>
                    {levelIcon(p.next_escalation_level)}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-medium text-slate-800 text-sm">{p.senior_name}</span>
                        <Badge className={severityColor(p.severity)}>{p.severity}</Badge>
                        <span className="text-xs text-slate-400">{p.device_identifier}</span>
                      </div>
                      <p className="text-xs text-slate-500">{p.incident_type.replace(/_/g, ' ')} — age: {p.age_minutes}min</p>
                    </div>
                    <div className="text-right shrink-0">
                      <p className={`text-sm font-mono font-bold ${
                        p.overdue ? 'text-red-600' :
                        p.time_remaining_seconds < 60 ? 'text-amber-600' : 'text-slate-600'
                      }`} data-testid={`countdown-${p.incident_id}`}>
                        {formatTime(p.time_remaining_seconds)}
                      </p>
                      <p className="text-[10px] text-slate-400">→ L{p.next_escalation_level}</p>
                    </div>
                    <Button
                      size="sm"
                      variant="outline"
                      className="shrink-0 h-8 text-xs border-green-300 text-green-700 hover:bg-green-50"
                      onClick={() => handleAcknowledge(p.incident_id)}
                      disabled={acknowledging[p.incident_id]}
                      data-testid={`ack-btn-${p.incident_id}`}
                    >
                      {acknowledging[p.incident_id] ? <Loader2 className="w-3 h-3 animate-spin" /> : <CheckCircle className="w-3 h-3 mr-1" />}
                      Ack
                    </Button>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Escalation History */}
      {history && history.length > 0 && (
        <Card data-testid="escalation-history-card">
          <CardContent className="p-5">
            <h3 className="text-lg font-semibold text-slate-800 mb-3 flex items-center gap-2">
              <ArrowUpRight className="w-5 h-5 text-purple-500" />
              Recent Escalation History
            </h3>
            <div className="space-y-2" data-testid="history-list">
              {history.map(h => (
                <div key={h.incident_id} className="flex items-center gap-3 p-2.5 rounded border border-slate-100 bg-slate-50/50 text-sm" data-testid={`history-${h.incident_id}`}>
                  {levelIcon(h.escalation_level)}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-slate-700">{h.senior_name}</span>
                      <Badge className={severityColor(h.severity)}>{h.severity}</Badge>
                      <span className="text-xs text-slate-400">{h.incident_type.replace(/_/g, ' ')}</span>
                    </div>
                    <div className="flex gap-2 text-[10px] text-slate-400 mt-0.5">
                      <span>L{h.escalation_level}</span>
                      {h.acknowledged_at && (
                        <span className="text-green-600">Acked by {h.acknowledged_by || '—'} ({h.response_time_min}min)</span>
                      )}
                      <span>{h.status}</span>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <button
                      onClick={() => handleSmartRec(h.incident_id)}
                      disabled={smartRec[h.incident_id]?.loading}
                      className="flex items-center gap-1 px-2 py-1 rounded bg-purple-50 border border-purple-200 text-purple-700 text-[10px] hover:bg-purple-100 transition-colors disabled:opacity-50"
                      data-testid={`smart-rec-btn-${h.incident_id}`}
                    >
                      {smartRec[h.incident_id]?.loading ? <Loader2 className="w-3 h-3 animate-spin" /> : <Brain className="w-3 h-3" />}
                      AI
                    </button>
                    <div className="text-right">
                      <p className="text-xs text-slate-500">
                        {new Date(h.created_at).toLocaleDateString()} {new Date(h.created_at).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'})}
                      </p>
                      {h.acknowledged_at ? (
                        <Badge className="bg-green-50 text-green-600 text-[10px]">Acknowledged</Badge>
                      ) : h.status === 'resolved' ? (
                        <Badge className="bg-blue-50 text-blue-600 text-[10px]">Resolved</Badge>
                      ) : (
                        <Badge className="bg-red-50 text-red-600 text-[10px]">Unacknowledged</Badge>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>

            {/* Smart Recommendation Inline Display */}
            {Object.entries(smartRec).filter(([_, v]) => v.data).map(([iid, v]) => (
              <div key={iid} className="mt-3 p-3 rounded-lg border border-purple-200 bg-purple-50/50" data-testid={`smart-rec-detail-${iid}`}>
                <div className="flex items-center gap-2 mb-2">
                  <Brain className="w-4 h-4 text-purple-600" />
                  <span className="font-semibold text-sm text-purple-800">AI Adaptive Recommendation</span>
                  <span className="text-xs text-slate-400 ml-auto">{v.data.senior_name}</span>
                </div>
                <div className="grid grid-cols-3 gap-2 mb-2">
                  {['l1', 'l2', 'l3'].map(level => {
                    const adaptive = v.data.timers[level];
                    const static_ = v.data.static_timers[level];
                    const diff = adaptive - static_;
                    return (
                      <div key={level} className="p-2 rounded bg-white border border-slate-100 text-center" data-testid={`smart-timer-${level}`}>
                        <p className="text-[10px] text-slate-400 uppercase">{level.toUpperCase()}</p>
                        <p className="text-lg font-bold text-purple-700">{adaptive === 0 ? 'SKIP' : `${adaptive}m`}</p>
                        <p className={`text-[10px] ${diff < 0 ? 'text-green-600' : diff > 0 ? 'text-red-500' : 'text-slate-400'}`}>
                          {diff === 0 ? 'same' : `${diff > 0 ? '+' : ''}${diff.toFixed(1)}m`}
                        </p>
                      </div>
                    );
                  })}
                </div>
                {v.data.skip_l1 && (
                  <div className="flex items-center gap-1.5 px-2 py-1 rounded bg-amber-50 border border-amber-200 mb-2">
                    <AlertTriangle className="w-3 h-3 text-amber-500" />
                    <span className="text-xs text-amber-700 font-medium">L1 SKIP recommended — guardian unreliable for this pattern</span>
                  </div>
                )}
                {v.data.reasons?.length > 0 && (
                  <div className="space-y-0.5">
                    {v.data.reasons.map((r, i) => (
                      <p key={i} className="text-[10px] text-slate-500 flex items-center gap-1">
                        <ChevronRight className="w-3 h-3 text-purple-400" /> {r}
                      </p>
                    ))}
                  </div>
                )}
                {v.data.guardian_profile_summary && (
                  <div className="mt-2 flex gap-3 text-[10px] text-slate-400">
                    <span>Response rate: <strong className="text-slate-600">{(v.data.guardian_profile_summary.response_rate * 100).toFixed(0)}%</strong></span>
                    <span>Avg: <strong className="text-slate-600">{v.data.guardian_profile_summary.avg_response_minutes ?? '—'}min</strong></span>
                    <span>Reliability: <strong className="text-slate-600">{v.data.guardian_profile_summary.reliability_score}/100</strong></span>
                  </div>
                )}
              </div>
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
