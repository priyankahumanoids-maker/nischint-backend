import { useState, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Badge } from './ui/badge';
import { Progress } from './ui/progress';
import { Activity, Battery, Wifi, Shield, AlertTriangle, Clock } from 'lucide-react';
import api from '../api';
import DeviceStatusBadge from './DeviceStatusBadge';
import { formatRelativeTime } from '../utils/time';

function reliabilityColor(score) {
  if (score >= 80) return 'text-green-600';
  if (score >= 60) return 'text-yellow-600';
  return 'text-red-600';
}

function reliabilityBg(score) {
  if (score >= 80) return 'bg-green-100 text-green-700';
  if (score >= 60) return 'bg-yellow-100 text-yellow-700';
  return 'bg-red-100 text-red-700';
}

function batteryColor(level) {
  if (level === null || level === undefined) return 'text-slate-400';
  if (level >= 60) return 'text-green-600';
  if (level >= 20) return 'text-yellow-600';
  return 'text-red-600';
}

function signalLabel(dbm) {
  if (dbm === null || dbm === undefined) return { label: 'N/A', color: 'text-slate-400' };
  if (dbm >= -50) return { label: 'Excellent', color: 'text-green-600' };
  if (dbm >= -70) return { label: 'Good', color: 'text-teal-600' };
  if (dbm >= -80) return { label: 'Fair', color: 'text-yellow-600' };
  return { label: 'Poor', color: 'text-red-600' };
}

export default function DeviceHealthCard({ seniorId, token }) {
  const [healthData, setHealthData] = useState([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!seniorId) return;
    setLoading(true);
    api.get(`/my/seniors/${seniorId}/device-health?window_hours=24`)
      .then(res => setHealthData(res.data))
      .catch(() => setHealthData([]))
      .finally(() => setLoading(false));
  }, [seniorId]);

  if (!seniorId) return null;
  if (loading) return <div className="text-sm text-slate-400 py-4" data-testid="device-health-loading">Loading device health...</div>;
  if (!healthData.length) return null;

  return (
    <div className="space-y-4" data-testid="device-health-section">
      {healthData.map((d) => {
        const sig = signalLabel(d.signal?.latest);
        return (
          <Card key={d.device_id} className="border border-slate-200" data-testid={`device-health-${d.device_id}`}>
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <CardTitle className="text-base font-semibold flex items-center gap-2">
                  <Activity className="w-4 h-4 text-teal-500" />
                  {d.device_identifier}
                </CardTitle>
                <div className="flex items-center gap-2">
                  <Badge className={reliabilityBg(d.reliability_score)} data-testid={`reliability-score-${d.device_id}`}>
                    <Shield className="w-3 h-3 mr-1" />
                    {d.reliability_score}/100
                  </Badge>
                  <DeviceStatusBadge status={d.last_seen ? d.status : null} />
                </div>
              </div>
              <p className="text-xs text-muted-foreground flex items-center gap-1">
                <Clock className="w-3 h-3" />
                Last seen: {formatRelativeTime(d.last_seen)}
              </p>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                {/* Uptime */}
                <div className="space-y-1.5">
                  <p className="text-xs font-medium text-slate-500 uppercase tracking-wide">Uptime (24h)</p>
                  <p className={`text-xl font-bold ${reliabilityColor(d.uptime_percent)}`} data-testid={`uptime-${d.device_id}`}>
                    {d.uptime_percent}%
                  </p>
                  <Progress value={d.uptime_percent} className="h-1.5" />
                  <p className="text-xs text-slate-400">{d.heartbeat_count} heartbeats</p>
                </div>

                {/* Battery */}
                <div className="space-y-1.5">
                  <p className="text-xs font-medium text-slate-500 uppercase tracking-wide">Battery</p>
                  <div className="flex items-center gap-1.5">
                    <Battery className={`w-5 h-5 ${batteryColor(d.battery?.latest)}`} />
                    <span className={`text-xl font-bold ${batteryColor(d.battery?.latest)}`} data-testid={`battery-${d.device_id}`}>
                      {d.battery?.latest !== null && d.battery?.latest !== undefined ? `${d.battery.latest}%` : 'N/A'}
                    </span>
                  </div>
                  {d.battery?.average !== null && d.battery?.average !== undefined && (
                    <p className="text-xs text-slate-400">Avg: {d.battery.average}% | Min: {d.battery.min ?? 'N/A'}%</p>
                  )}
                </div>

                {/* Signal */}
                <div className="space-y-1.5">
                  <p className="text-xs font-medium text-slate-500 uppercase tracking-wide">Signal</p>
                  <div className="flex items-center gap-1.5">
                    <Wifi className={`w-5 h-5 ${sig.color}`} />
                    <span className={`text-xl font-bold ${sig.color}`} data-testid={`signal-${d.device_id}`}>
                      {d.signal?.latest !== null && d.signal?.latest !== undefined ? `${d.signal.latest} dBm` : 'N/A'}
                    </span>
                  </div>
                  <p className={`text-xs ${sig.color}`}>{sig.label}</p>
                </div>

                {/* Offline Events */}
                <div className="space-y-1.5">
                  <p className="text-xs font-medium text-slate-500 uppercase tracking-wide">Offline Events</p>
                  <div className="flex items-center gap-1.5">
                    <AlertTriangle className={`w-5 h-5 ${d.offline_count > 0 ? 'text-red-500' : 'text-slate-300'}`} />
                    <span className={`text-xl font-bold ${d.offline_count > 0 ? 'text-red-600' : 'text-slate-600'}`} data-testid={`offline-count-${d.device_id}`}>
                      {d.offline_count}
                    </span>
                  </div>
                  <p className="text-xs text-slate-400">in last 24h</p>
                </div>
              </div>
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}
