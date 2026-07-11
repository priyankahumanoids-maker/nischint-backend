import React, { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Badge } from './ui/badge';
import { operatorApi } from '../api';
import {
  TrendingDown, Moon, MapPin, HeartPulse, Loader2, AlertTriangle, Clock, ShieldAlert,
} from 'lucide-react';

const PREDICTION_ICONS = {
  activity_decline: { icon: TrendingDown, color: 'text-orange-600', bg: 'bg-orange-100' },
  sleep_disruption: { icon: Moon, color: 'text-indigo-600', bg: 'bg-indigo-100' },
  wandering_risk: { icon: MapPin, color: 'text-purple-600', bg: 'bg-purple-100' },
  health_decline: { icon: HeartPulse, color: 'text-red-600', bg: 'bg-red-100' },
};

const PREDICTION_LABELS = {
  activity_decline: 'Activity Declining',
  sleep_disruption: 'Sleep Disruption',
  wandering_risk: 'Wandering Risk',
  health_decline: 'Health Decline',
};

export function PredictiveAlertsPanel() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetch = useCallback(async () => {
    try {
      const res = await operatorApi.getFleetPredictiveAlerts();
      setData(res.data);
    } catch {
      // Silent — panel is supplementary
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetch(); }, [fetch]);

  if (loading) {
    return (
      <Card className="border border-amber-100" data-testid="predictive-alerts-loading">
        <CardContent className="p-4 flex items-center justify-center gap-2 text-slate-400 text-sm">
          <Loader2 className="w-4 h-4 animate-spin" /> Loading predictive alerts...
        </CardContent>
      </Card>
    );
  }

  const alerts = data?.alerts || [];

  return (
    <Card className={`border ${alerts.length > 0 ? 'border-amber-300' : 'border-slate-200'}`}
      data-testid="predictive-alerts-panel">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <ShieldAlert className="w-4 h-4 text-amber-600" />
            <CardTitle className="text-sm">Predictive Alerts</CardTitle>
            {alerts.length > 0 && (
              <Badge className="text-[10px] bg-amber-500 text-white">{alerts.length}</Badge>
            )}
          </div>
          <span className="text-[10px] text-slate-400">Advance warnings</span>
        </div>
      </CardHeader>
      <CardContent>
        {alerts.length === 0 ? (
          <div className="text-center py-4 text-slate-400" data-testid="predictive-no-alerts">
            <ShieldAlert className="w-6 h-6 mx-auto mb-1 opacity-20" />
            <p className="text-xs">No predictive alerts active</p>
            <p className="text-[10px] mt-0.5">All devices within expected trends</p>
          </div>
        ) : (
          <div className="space-y-2">
            {alerts.map((a, i) => {
              const meta = PREDICTION_ICONS[a.prediction_type] || PREDICTION_ICONS.health_decline;
              const Icon = meta.icon;
              return (
                <div key={i} className="flex items-start gap-2.5 p-2 rounded-lg bg-amber-50/50 border border-amber-100"
                  data-testid={`predictive-alert-${i}`}>
                  <div className={`p-1.5 rounded-md ${meta.bg}`}>
                    <Icon className={`w-3.5 h-3.5 ${meta.color}`} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5">
                      <span className="text-xs font-semibold text-slate-800">{a.device_identifier}</span>
                      <Badge variant="outline" className="text-[9px] bg-amber-100 text-amber-700 border-amber-200">
                        {PREDICTION_LABELS[a.prediction_type] || a.prediction_type}
                      </Badge>
                    </div>
                    <p className="text-[10px] text-slate-600 mt-0.5 truncate" title={a.explanation}>
                      {a.explanation}
                    </p>
                    <div className="flex items-center gap-2 mt-1 text-[9px] text-slate-400">
                      <span className="font-semibold text-amber-600">{(a.prediction_score * 100).toFixed(0)}% risk</span>
                      <span>·</span>
                      <Clock className="w-2.5 h-2.5" />
                      <span>Risk in {a.prediction_window_hours}h</span>
                      <span>·</span>
                      <span>{(a.confidence * 100).toFixed(0)}% conf</span>
                    </div>
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
