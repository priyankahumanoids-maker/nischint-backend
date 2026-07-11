import React, { useState, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../ui/card';
import { Badge } from '../ui/badge';
import {
  Shield, Clock, CheckCircle, AlertTriangle, TrendingUp,
  Users, Loader2, RefreshCw, ArrowUp, ArrowDown,
} from 'lucide-react';
import { Button } from '../ui/button';
import api from '../../api';
import { toast } from 'sonner';

const formatTime = (seconds) => {
  if (!seconds || seconds <= 0) return '--';
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  const h = Math.floor(seconds / 3600);
  const m = Math.round((seconds % 3600) / 60);
  return `${h}h ${m}m`;
};

export default function GuardianMetrics() {
  const [metrics, setMetrics] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchMetrics = async () => {
    try {
      const res = await api.get('/incidents/metrics/response');
      setMetrics(res.data);
    } catch {
      toast.error('Failed to load metrics');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchMetrics();
    const iv = setInterval(fetchMetrics, 30000);
    return () => clearInterval(iv);
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-48" data-testid="guardian-metrics-loading">
        <Loader2 className="w-8 h-8 animate-spin text-teal-500" />
      </div>
    );
  }

  if (!metrics) return null;

  const ackRate = metrics.acknowledgment_rate_pct || 0;
  const ackColor = ackRate >= 80 ? 'text-emerald-500' : ackRate >= 50 ? 'text-amber-500' : 'text-red-500';
  const hasData = (metrics.total_incidents || 0) > 0;

  return (
    <div className="space-y-6" data-testid="guardian-metrics">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold text-slate-800">Guardian Response Metrics</h2>
        <Button variant="outline" size="sm" onClick={fetchMetrics} data-testid="metrics-refresh-btn">
          <RefreshCw className="w-4 h-4 mr-2" /> Refresh
        </Button>
      </div>

      <p className="text-sm text-slate-500">Last {metrics.period} performance overview</p>

      {/* Empty state helper — shown when no incidents have occurred yet */}
      {!hasData && (
        <Card className="border-dashed border-slate-300 bg-slate-50" data-testid="metrics-empty-state">
          <CardContent className="p-6">
            <div className="flex items-start gap-3">
              <div className="w-10 h-10 rounded-xl bg-emerald-100 flex items-center justify-center flex-shrink-0">
                <CheckCircle className="w-5 h-5 text-emerald-600" />
              </div>
              <div>
                <p className="font-semibold text-slate-700">No incidents in the last {metrics.period} — that&apos;s a good thing.</p>
                <p className="text-sm text-slate-500 mt-1">
                  Response metrics (Ack rate, Avg response, Guardian performance) are computed from real
                  incidents. They populate automatically once SOS, fall, or high-risk events happen.
                </p>
                <p className="text-xs text-slate-400 mt-2">
                  Want to test the system? Trigger a test SOS from the mobile app, and numbers here will update live.
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* KPI Cards */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4" data-testid="metrics-kpi-grid">
        <Card className="border-l-4 border-l-blue-500">
          <CardContent className="p-4">
            <p className="text-xs font-medium text-slate-500 uppercase">Total Incidents</p>
            <p className="text-3xl font-bold text-slate-800 mt-1" data-testid="metric-total">{metrics.total_incidents}</p>
          </CardContent>
        </Card>

        <Card className="border-l-4 border-l-red-500">
          <CardContent className="p-4">
            <p className="text-xs font-medium text-slate-500 uppercase">Active / Open</p>
            <p className="text-3xl font-bold text-red-600 mt-1" data-testid="metric-active">{metrics.active_unresolved}</p>
          </CardContent>
        </Card>

        <Card className="border-l-4 border-l-teal-500">
          <CardContent className="p-4">
            <p className="text-xs font-medium text-slate-500 uppercase">Acknowledged</p>
            <p className="text-3xl font-bold text-teal-600 mt-1" data-testid="metric-ack">{metrics.acknowledged_count}</p>
          </CardContent>
        </Card>

        <Card className="border-l-4 border-l-green-500">
          <CardContent className="p-4">
            <p className="text-xs font-medium text-slate-500 uppercase">Resolved</p>
            <p className="text-3xl font-bold text-green-600 mt-1" data-testid="metric-resolved">{metrics.resolved_count}</p>
          </CardContent>
        </Card>

        <Card className="border-l-4 border-l-orange-500">
          <CardContent className="p-4">
            <p className="text-xs font-medium text-slate-500 uppercase">Escalated</p>
            <p className="text-3xl font-bold text-orange-600 mt-1" data-testid="metric-escalated">{metrics.escalation_count}</p>
          </CardContent>
        </Card>

        <Card className="border-l-4 border-l-purple-500">
          <CardContent className="p-4">
            <p className="text-xs font-medium text-slate-500 uppercase">Ack Rate</p>
            <p className={`text-3xl font-bold mt-1 ${ackColor}`} data-testid="metric-ack-rate">
              {ackRate}%
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Response Time Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card data-testid="avg-response-card">
          <CardContent className="p-6">
            <div className="flex items-center gap-3">
              <div className="w-12 h-12 rounded-xl bg-amber-100 flex items-center justify-center">
                <Clock className="w-6 h-6 text-amber-600" />
              </div>
              <div>
                <p className="text-sm text-slate-500">Avg Response Time</p>
                <p className="text-2xl font-bold text-slate-800" data-testid="metric-avg-response">
                  {formatTime(metrics.avg_response_seconds)}
                </p>
                <p className="text-xs text-slate-400">Time from incident creation to acknowledgment</p>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card data-testid="avg-resolution-card">
          <CardContent className="p-6">
            <div className="flex items-center gap-3">
              <div className="w-12 h-12 rounded-xl bg-emerald-100 flex items-center justify-center">
                <CheckCircle className="w-6 h-6 text-emerald-600" />
              </div>
              <div>
                <p className="text-sm text-slate-500">Avg Resolution Time</p>
                <p className="text-2xl font-bold text-slate-800" data-testid="metric-avg-resolution">
                  {formatTime(metrics.avg_resolution_seconds)}
                </p>
                <p className="text-xs text-slate-400">Time from incident creation to resolution</p>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Guardian Leaderboard */}
      {metrics.guardians?.length > 0 && (
        <Card data-testid="guardian-leaderboard">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg">
              <Users className="w-5 h-5 text-purple-500" />
              Guardian Performance
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-100">
                    <th className="text-left py-2 px-3 text-slate-500 font-medium">Guardian</th>
                    <th className="text-center py-2 px-3 text-slate-500 font-medium">Incidents</th>
                    <th className="text-center py-2 px-3 text-slate-500 font-medium">Acknowledged</th>
                    <th className="text-center py-2 px-3 text-slate-500 font-medium">Ack Rate</th>
                    <th className="text-center py-2 px-3 text-slate-500 font-medium">Avg Response</th>
                  </tr>
                </thead>
                <tbody>
                  {metrics.guardians.map((g, i) => {
                    const gAckRate = g.incidents > 0 ? Math.round((g.acknowledged / g.incidents) * 100) : 0;
                    const gAckColor = gAckRate >= 80 ? 'bg-emerald-100 text-emerald-700' : gAckRate >= 50 ? 'bg-amber-100 text-amber-700' : 'bg-red-100 text-red-700';
                    return (
                      <tr key={i} className="border-b border-slate-50 hover:bg-slate-50" data-testid={`guardian-row-${i}`}>
                        <td className="py-2.5 px-3 font-medium text-slate-700">{g.name}</td>
                        <td className="py-2.5 px-3 text-center">{g.incidents}</td>
                        <td className="py-2.5 px-3 text-center">{g.acknowledged}</td>
                        <td className="py-2.5 px-3 text-center">
                          <Badge className={gAckColor}>{gAckRate}%</Badge>
                        </td>
                        <td className="py-2.5 px-3 text-center font-mono text-slate-600">
                          {formatTime(g.avg_response_seconds)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
