import React, { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { operatorApi } from '../api';
import { toast } from 'sonner';
import {
  Users, RefreshCw, Loader2, MapPin, AlertTriangle, Eye,
  Activity, Shield, Radio, TrendingUp, Clock,
} from 'lucide-react';

const RISK_COLORS = {
  critical: { bg: 'bg-red-100 text-red-700', ring: 'border-red-200 bg-red-50/50' },
  high: { bg: 'bg-orange-100 text-orange-700', ring: 'border-orange-200 bg-orange-50/50' },
  medium: { bg: 'bg-amber-100 text-amber-700', ring: 'border-amber-200 bg-amber-50/50' },
  low: { bg: 'bg-green-100 text-green-700', ring: 'border-slate-100 bg-slate-50/50' },
};

function SignalBar({ label, value, max = 1 }) {
  const pct = Math.min(100, (value / max) * 100);
  const color = pct >= 70 ? 'bg-red-400' : pct >= 40 ? 'bg-orange-400' : pct >= 20 ? 'bg-amber-400' : 'bg-green-400';
  return (
    <div className="flex items-center gap-2">
      <span className="text-[10px] text-slate-500 w-24 shrink-0">{label}</span>
      <div className="flex-1 h-2 bg-slate-100 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-[10px] font-medium text-slate-600 w-10 text-right">{(value * 100).toFixed(0)}%</span>
    </div>
  );
}

function AssessmentDetail({ data, onClose }) {
  if (!data) return null;
  const sig = data.signals || {};
  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" onClick={onClose} data-testid="activity-detail-modal">
      <div className="bg-white rounded-xl shadow-2xl max-w-md w-full max-h-[80vh] overflow-y-auto p-5" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-lg font-bold text-slate-800">{data.zone_name || data.device_name || 'Location Assessment'}</h3>
            <div className="flex items-center gap-2 mt-1">
              <Badge className={RISK_COLORS[data.activity_risk_level || data.risk_level]?.bg || 'bg-slate-100 text-slate-600'}>
                {data.activity_risk_level || data.risk_level}
              </Badge>
              <span className="text-xs text-slate-400">Score: {data.activity_risk_score ?? data.risk_score}</span>
            </div>
          </div>
          <Button variant="ghost" size="sm" onClick={onClose}>x</Button>
        </div>

        <div className="space-y-3">
          <Card className="border-slate-100">
            <CardContent className="p-3">
              <p className="text-sm font-semibold text-slate-700 mb-2">Activity Signals</p>
              <div className="space-y-2">
                <SignalBar label="Crowd Density" value={sig.crowd_density || 0} />
                <SignalBar label="Traffic Risk" value={sig.traffic_corridor || 0} />
                <SignalBar label="Temporal Spike" value={sig.temporal_spike || 0} />
                <SignalBar label="Hazard Zone" value={sig.hazard_zone || 0} />
                <SignalBar label="Emergency" value={sig.emergency_cluster || 0} />
                <SignalBar label="Acceleration" value={Math.max(0, sig.acceleration || 0)} />
              </div>
            </CardContent>
          </Card>

          {sig.peak_activity_hour >= 0 && (
            <div className="flex items-center gap-2 text-xs text-slate-500">
              <Clock className="w-3.5 h-3.5" /> Peak activity hour: {sig.peak_activity_hour}:00
              <span className="text-slate-300">|</span>
              Current hour activity: {((sig.hour_activity_level || 0) * 100).toFixed(0)}%
            </div>
          )}

          {(data.activity_factors || data.factors)?.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {(data.activity_factors || data.factors).map((f, i) => (
                <span key={i} className="text-[10px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 border border-slate-200">{f}</span>
              ))}
            </div>
          )}

          {data.incident_counts && (
            <div className="flex gap-3 text-[10px] text-slate-400">
              <span>Incidents within 500m: {data.incident_counts.within_500m}</span>
              <span>Within 1km: {data.incident_counts.within_1km}</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function HumanActivityRiskPage() {
  const [hotspots, setHotspots] = useState(null);
  const [fleet, setFleet] = useState(null);
  const [pointAssessment, setPointAssessment] = useState(null);
  const [loading, setLoading] = useState(true);
  const [fleetLoading, setFleetLoading] = useState(true);
  const [assessing, setAssessing] = useState(false);
  const [activeTab, setActiveTab] = useState('hotspots');
  const [detailData, setDetailData] = useState(null);
  const [assessLat, setAssessLat] = useState('12.971');
  const [assessLng, setAssessLng] = useState('77.594');

  const fetchHotspots = useCallback(async () => {
    setLoading(true);
    try { setHotspots((await operatorApi.getActivityHotspots()).data); }
    catch { toast.error('Failed to load activity hotspots'); }
    finally { setLoading(false); }
  }, []);

  const fetchFleet = useCallback(async () => {
    setFleetLoading(true);
    try { setFleet((await operatorApi.getFleetActivityRisk()).data); }
    catch { toast.error('Failed to load fleet activity risk'); }
    finally { setFleetLoading(false); }
  }, []);

  useEffect(() => { fetchHotspots(); fetchFleet(); }, [fetchHotspots, fetchFleet]);

  const handleAssessPoint = async () => {
    setAssessing(true);
    try {
      const res = await operatorApi.assessActivityRisk(parseFloat(assessLat), parseFloat(assessLng));
      setPointAssessment(res.data);
      toast.success(`Activity risk assessed: ${res.data.risk_level} (${res.data.risk_score})`);
    } catch { toast.error('Assessment failed'); }
    finally { setAssessing(false); }
  };

  if (loading && fleetLoading) return (
    <div className="flex items-center justify-center py-12"><Loader2 className="w-6 h-6 animate-spin text-slate-400" /></div>
  );

  return (
    <div className="space-y-6" data-testid="human-activity-risk-page">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold text-slate-800">Human Activity Risk AI</h2>
        <Button variant="outline" size="sm" onClick={() => { fetchHotspots(); fetchFleet(); }} data-testid="refresh-activity">
          <RefreshCw className="w-4 h-4 mr-2" /> Refresh
        </Button>
      </div>

      {/* Summary Cards */}
      {hotspots && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3" data-testid="activity-summary">
          {[
            { label: 'Zones Analyzed', value: hotspots.total_zones, icon: <MapPin className="w-5 h-5 text-purple-500" />, color: 'border-purple-200 bg-purple-50/50' },
            { label: 'High Activity', value: hotspots.high_activity_count, icon: <AlertTriangle className="w-5 h-5 text-red-500" />, color: 'border-red-200 bg-red-50/50' },
            { label: 'Crowd Zones', value: hotspots.crowd_zones_count, icon: <Users className="w-5 h-5 text-orange-500" />, color: 'border-orange-200 bg-orange-50/50' },
            { label: 'Hazard Zones', value: hotspots.hazard_zones_count, icon: <Shield className="w-5 h-5 text-amber-500" />, color: 'border-amber-200 bg-amber-50/50' },
          ].map(s => (
            <Card key={s.label} className={`border ${s.color}`}>
              <CardContent className="p-4 flex items-center gap-3">
                {s.icon}
                <div>
                  <p className="text-2xl font-bold text-slate-800">{s.value}</p>
                  <p className="text-xs text-slate-500">{s.label}</p>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Point Assessment */}
      <Card data-testid="point-assessment-card">
        <CardContent className="p-4">
          <div className="flex items-center gap-3 flex-wrap">
            <MapPin className="w-5 h-5 text-blue-500 shrink-0" />
            <span className="text-sm font-medium text-slate-700">Assess Location:</span>
            <Input value={assessLat} onChange={e => setAssessLat(e.target.value)} placeholder="Lat" className="h-8 text-xs w-24" data-testid="assess-lat" />
            <Input value={assessLng} onChange={e => setAssessLng(e.target.value)} placeholder="Lng" className="h-8 text-xs w-24" data-testid="assess-lng" />
            <Button size="sm" onClick={handleAssessPoint} disabled={assessing} className="h-8 bg-blue-600 hover:bg-blue-700" data-testid="assess-btn">
              {assessing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : 'Assess'}
            </Button>
            {pointAssessment && (
              <div className="flex items-center gap-2 ml-2">
                <Badge className={RISK_COLORS[pointAssessment.risk_level]?.bg}>{pointAssessment.risk_level}</Badge>
                <span className={`text-sm font-bold ${pointAssessment.risk_score >= 6 ? 'text-red-600' : pointAssessment.risk_score >= 4 ? 'text-orange-600' : 'text-green-600'}`}>{pointAssessment.risk_score}</span>
                <Button variant="ghost" size="sm" className="h-6 px-1" onClick={() => setDetailData(pointAssessment)}><Eye className="w-3 h-3" /></Button>
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Tabs */}
      <div className="flex gap-1 bg-slate-100 rounded-lg p-1" data-testid="activity-tab-switcher">
        {[
          { id: 'hotspots', label: 'Zone Activity', icon: <Activity className="w-4 h-4" /> },
          { id: 'fleet', label: 'Fleet Activity', icon: <Radio className="w-4 h-4" /> },
        ].map(tab => (
          <button key={tab.id} onClick={() => setActiveTab(tab.id)}
            className={`flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-md text-sm font-medium transition-colors ${
              activeTab === tab.id ? 'bg-white text-slate-800 shadow-sm' : 'text-slate-500 hover:text-slate-700'
            }`} data-testid={`activity-tab-${tab.id}`}>
            {tab.icon} {tab.label}
          </button>
        ))}
      </div>

      {/* Hotspots Tab */}
      {activeTab === 'hotspots' && hotspots && (
        <Card data-testid="activity-hotspots-card">
          <CardContent className="p-5">
            <h3 className="text-base font-semibold text-slate-800 mb-3 flex items-center gap-2">
              <Activity className="w-5 h-5 text-purple-500" /> Zone Activity Risk Analysis
              <Badge className="bg-purple-100 text-purple-700 ml-1">{hotspots.total_zones}</Badge>
            </h3>
            <div className="space-y-2 max-h-[500px] overflow-y-auto">
              {(hotspots.hotspots || []).map((h, i) => {
                const rc = RISK_COLORS[h.activity_risk_level] || RISK_COLORS.low;
                const sig = h.activity_signals || {};
                return (
                  <div key={i} className={`flex items-center gap-3 p-3 rounded-lg border ${rc.ring}`} data-testid={`activity-zone-${i}`}>
                    <div className="flex items-center gap-1 shrink-0">
                      <div className={`w-9 h-9 rounded-full flex items-center justify-center ${
                        h.zone_risk_score >= 7 ? 'bg-red-100' : h.zone_risk_score >= 5 ? 'bg-orange-100' : 'bg-amber-100'
                      }`}>
                        <span className={`text-xs font-bold ${h.zone_risk_score >= 7 ? 'text-red-600' : 'text-orange-600'}`}>{h.zone_risk_score}</span>
                      </div>
                      <span className="text-slate-300 text-xs">+</span>
                      <div className={`w-9 h-9 rounded-full flex items-center justify-center border-2 ${
                        h.activity_risk_score >= 6 ? 'bg-red-50 border-red-400' : h.activity_risk_score >= 4 ? 'bg-orange-50 border-orange-400' : 'bg-green-50 border-green-300'
                      }`}>
                        <span className={`text-xs font-bold ${h.activity_risk_score >= 6 ? 'text-red-600' : h.activity_risk_score >= 4 ? 'text-orange-600' : 'text-green-600'}`}>{h.activity_risk_score}</span>
                      </div>
                      <span className="text-slate-300 text-xs">=</span>
                      <div className={`w-9 h-9 rounded-full flex items-center justify-center bg-slate-800`}>
                        <span className="text-xs font-bold text-white">{h.combined_risk}</span>
                      </div>
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-medium text-slate-800 text-sm truncate">{h.zone_name}</span>
                        <Badge className={rc.bg}>{h.activity_risk_level}</Badge>
                      </div>
                      <div className="flex gap-2 text-[10px] text-slate-400 mt-0.5 flex-wrap">
                        {sig.crowd_density > 0.3 && <span className="px-1 rounded bg-orange-50 text-orange-500 border border-orange-100">crowd</span>}
                        {sig.hazard_zone > 0.3 && <span className="px-1 rounded bg-amber-50 text-amber-500 border border-amber-100">hazard</span>}
                        {sig.traffic_corridor > 0.3 && <span className="px-1 rounded bg-blue-50 text-blue-500 border border-blue-100">traffic</span>}
                        {sig.temporal_spike > 0.3 && <span className="px-1 rounded bg-purple-50 text-purple-500 border border-purple-100">spike</span>}
                        {sig.emergency_cluster > 0.3 && <span className="px-1 rounded bg-red-50 text-red-500 border border-red-100">emergency</span>}
                      </div>
                    </div>
                    <Button variant="ghost" size="sm" className="shrink-0 h-7 px-2" onClick={() => setDetailData(h)} data-testid={`view-activity-${i}`}><Eye className="w-3.5 h-3.5" /></Button>
                  </div>
                );
              })}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Fleet Tab */}
      {activeTab === 'fleet' && fleet && (
        <Card data-testid="fleet-activity-card">
          <CardContent className="p-5">
            <h3 className="text-base font-semibold text-slate-800 mb-3 flex items-center gap-2">
              <Radio className="w-5 h-5 text-blue-500" /> Fleet Device Activity Risk
              <Badge className="bg-blue-100 text-blue-700 ml-1">{fleet.total_devices}</Badge>
              {fleet.high_risk_count > 0 && <Badge className="bg-red-100 text-red-700">{fleet.high_risk_count} high risk</Badge>}
            </h3>
            <div className="space-y-2 max-h-[500px] overflow-y-auto">
              {(fleet.assessments || []).map((a, i) => {
                const rc = RISK_COLORS[a.risk_level] || RISK_COLORS.low;
                return (
                  <div key={i} className={`flex items-center gap-3 p-3 rounded-lg border ${rc.ring}`} data-testid={`fleet-device-${i}`}>
                    <div className={`w-10 h-10 rounded-full flex items-center justify-center shrink-0 ${
                      a.risk_score >= 6 ? 'bg-red-100' : a.risk_score >= 4 ? 'bg-orange-100' : 'bg-green-100'
                    }`}>
                      <span className={`text-sm font-bold ${a.risk_score >= 6 ? 'text-red-600' : a.risk_score >= 4 ? 'text-orange-600' : 'text-green-600'}`}>{a.risk_score}</span>
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-medium text-slate-800 text-sm">{a.device_name}</span>
                        <span className="text-xs text-slate-400">({a.senior_name})</span>
                        <Badge className={rc.bg}>{a.risk_level}</Badge>
                      </div>
                      <div className="flex gap-2 text-[10px] text-slate-400 mt-0.5">
                        <span className="flex items-center gap-0.5"><MapPin className="w-3 h-3" />{a.lat.toFixed(4)}, {a.lng.toFixed(4)}</span>
                        {a.factors?.slice(0, 3).map((f, j) => (
                          <span key={j} className="px-1 rounded bg-slate-50 border border-slate-200">{f}</span>
                        ))}
                      </div>
                    </div>
                    <Button variant="ghost" size="sm" className="shrink-0 h-7 px-2" onClick={() => setDetailData(a)} data-testid={`view-fleet-activity-${i}`}><Eye className="w-3.5 h-3.5" /></Button>
                  </div>
                );
              })}
            </div>
          </CardContent>
        </Card>
      )}

      <AssessmentDetail data={detailData} onClose={() => setDetailData(null)} />
    </div>
  );
}
