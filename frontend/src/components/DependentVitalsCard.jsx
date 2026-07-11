// HC-02 — Dependent Vitals by Device card.
//
// Renders the operator-facing per-device timeline served by
// `GET /api/health-signals/dependent/{dependent_id}/by-device`. One mini
// panel per paired device, so operators can tell multiple devices on a
// single dependent apart on the timeline. Compact summary + mini
// sparkline per signal type (HR / SpO₂) per device.
//
// Backend contract (HC-02):
//   { dependent_id, hours, devices: [{
//       device_id, device_model, sample_count, breach_count,
//       first_seen, last_seen,
//       samples: [{ ts, type, value, unit, breach_tag }]
//   }] }

import { useEffect, useMemo, useState } from 'react';
import { Card, CardContent } from './ui/card';
import { Badge } from './ui/badge';
import { Button } from './ui/button';
import { Loader2, RefreshCw, HeartPulse, Activity, AlertTriangle, Smartphone } from 'lucide-react';
import { LineChart, Line, ResponsiveContainer, YAxis, Tooltip as RTooltip } from 'recharts';
import api from '../api';

const HR_HIGH = 120;
const SPO2_LOW = 94;

// Mask a device_id to last 4 chars so operators can tell devices apart
// without rendering full hardware identifiers on screen.
function maskDeviceId(id) {
  if (!id) return '—';
  const s = String(id);
  if (s.length <= 6) return s;
  return `…${s.slice(-4)}`;
}

function relTime(iso) {
  if (!iso) return '—';
  const ts = new Date(iso).getTime();
  if (Number.isNaN(ts)) return '—';
  const diff = Math.max(0, Date.now() - ts);
  const m = Math.floor(diff / 60000);
  if (m < 1) return 'just now';
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function MiniSparkline({ samples, color, threshold, thresholdDir = 'high' }) {
  // `thresholdDir`: 'high' → breach when value > threshold; 'low' → value < threshold.
  if (!samples || samples.length < 2) {
    return (
      <div
        className="h-[32px] flex items-center text-[10px] text-slate-300"
        data-testid="dvc-sparkline-empty"
      >
        Insufficient data
      </div>
    );
  }
  const data = samples.map((s, i) => ({ i, v: s.value, ts: s.ts }));
  return (
    <ResponsiveContainer width="100%" height={32}>
      <LineChart data={data} margin={{ top: 2, right: 2, bottom: 2, left: 2 }}>
        <YAxis hide domain={['dataMin', 'dataMax']} />
        <RTooltip
          contentStyle={{
            fontSize: 11, padding: '4px 6px', background: 'rgba(255,255,255,0.95)',
            border: '1px solid #e2e8f0', borderRadius: 6,
          }}
          labelFormatter={() => ''}
          formatter={(value, _name, item) => {
            const ts = item?.payload?.ts;
            const isBreach = threshold != null && (
              thresholdDir === 'high' ? value > threshold : value < threshold
            );
            return [`${value}${isBreach ? '  ⚠' : ''}`, ts ? new Date(ts).toLocaleTimeString() : ''];
          }}
        />
        <Line
          type="monotone"
          dataKey="v"
          stroke={color}
          strokeWidth={1.6}
          dot={(props) => {
            const v = props.payload.v;
            const isBreach = threshold != null && (
              thresholdDir === 'high' ? v > threshold : v < threshold
            );
            return (
              <circle
                key={`${props.payload.ts}-${v}`}
                cx={props.cx}
                cy={props.cy}
                r={isBreach ? 2.5 : 1.4}
                fill={isBreach ? '#ef4444' : color}
              />
            );
          }}
          isAnimationActive={false}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}

function DevicePanel({ device }) {
  const samples = device.samples || [];
  const hr = samples.filter(s => s.type === 'heart_rate');
  const spo2 = samples.filter(s => s.type === 'spo2');
  const lastHr = hr.length ? hr[hr.length - 1] : null;
  const lastSpo2 = spo2.length ? spo2[spo2.length - 1] : null;
  const isPg = device.breach_count > 0;
  const last5Hr = hr.slice(-5);
  const last5Spo2 = spo2.slice(-5);

  return (
    <div
      className="rounded-lg border border-slate-200 bg-white p-3 space-y-2"
      data-testid={`dvc-device-${device.device_id || 'unknown'}`}
    >
      {/* header */}
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5">
            <Smartphone className="w-3.5 h-3.5 text-slate-400 shrink-0" />
            <span
              className="text-sm font-medium text-slate-800 truncate"
              data-testid="dvc-device-model"
            >
              {device.device_model || 'unknown'}
            </span>
          </div>
          <p
            className="text-[11px] text-slate-400 font-mono mt-0.5"
            title={device.device_id || ''}
            data-testid="dvc-device-id"
          >
            {maskDeviceId(device.device_id)}
          </p>
        </div>
        {isPg ? (
          <Badge
            className="bg-red-50 text-red-700 border border-red-200 text-[10px]"
            data-testid="dvc-breach-badge"
          >
            <AlertTriangle className="w-3 h-3 mr-1" />{device.breach_count}
          </Badge>
        ) : (
          <Badge
            className="bg-emerald-50 text-emerald-700 border border-emerald-200 text-[10px]"
            data-testid="dvc-clean-badge"
          >
            clean
          </Badge>
        )}
      </div>

      {/* counters */}
      <div className="grid grid-cols-3 gap-2 text-[11px] text-slate-500">
        <div>
          <p className="text-slate-400">Samples</p>
          <p className="font-semibold text-slate-700" data-testid="dvc-sample-count">
            {device.sample_count}
          </p>
        </div>
        <div>
          <p className="text-slate-400">First seen</p>
          <p className="text-slate-700" title={device.first_seen || ''}>{relTime(device.first_seen)}</p>
        </div>
        <div>
          <p className="text-slate-400">Last seen</p>
          <p className="text-slate-700" title={device.last_seen || ''}>{relTime(device.last_seen)}</p>
        </div>
      </div>

      {/* HR row */}
      <div className="border-t border-slate-100 pt-2">
        <div className="flex items-center justify-between text-[11px]">
          <div className="flex items-center gap-1.5">
            <HeartPulse className="w-3 h-3 text-rose-500" />
            <span className="text-slate-500">HR</span>
          </div>
          <span
            className={lastHr && lastHr.value > HR_HIGH ? 'text-red-600 font-semibold' : 'text-slate-700'}
            data-testid="dvc-hr-latest"
          >
            {lastHr ? `${Math.round(lastHr.value)} bpm` : '—'}
          </span>
        </div>
        <div className="mt-1">
          <MiniSparkline samples={hr} color="#f43f5e" threshold={HR_HIGH} thresholdDir="high" />
        </div>
        {last5Hr.length > 0 && (
          <div
            className="text-[10px] text-slate-400 font-mono truncate mt-1"
            data-testid="dvc-hr-last5"
          >
            last 5: {last5Hr.map(s => Math.round(s.value)).join(', ')}
          </div>
        )}
      </div>

      {/* SpO2 row */}
      <div className="border-t border-slate-100 pt-2">
        <div className="flex items-center justify-between text-[11px]">
          <div className="flex items-center gap-1.5">
            <Activity className="w-3 h-3 text-sky-500" />
            <span className="text-slate-500">SpO₂</span>
          </div>
          <span
            className={lastSpo2 && lastSpo2.value < SPO2_LOW ? 'text-red-600 font-semibold' : 'text-slate-700'}
            data-testid="dvc-spo2-latest"
          >
            {lastSpo2 ? `${lastSpo2.value.toFixed(1)}%` : '—'}
          </span>
        </div>
        <div className="mt-1">
          <MiniSparkline samples={spo2} color="#0ea5e9" threshold={SPO2_LOW} thresholdDir="low" />
        </div>
        {last5Spo2.length > 0 && (
          <div
            className="text-[10px] text-slate-400 font-mono truncate mt-1"
            data-testid="dvc-spo2-last5"
          >
            last 5: {last5Spo2.map(s => s.value.toFixed(1)).join(', ')}
          </div>
        )}
      </div>
    </div>
  );
}

export function DependentVitalsCard({ dependentId, dependentName, hours = 24 }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState(null);

  const fetchData = useMemo(() => async () => {
    if (!dependentId) return;
    setLoading(true);
    setErr(null);
    try {
      const res = await api.get(
        `/health-signals/dependent/${dependentId}/by-device`,
        { params: { hours } }
      );
      setData(res.data);
    } catch (e) {
      const msg = e?.response?.data?.detail || e?.message || 'Failed to load vitals';
      setErr(typeof msg === 'string' ? msg : 'Failed to load vitals');
    } finally {
      setLoading(false);
    }
  }, [dependentId, hours]);

  useEffect(() => { fetchData(); }, [fetchData]);

  if (!dependentId) {
    return (
      <Card data-testid="dvc-empty">
        <CardContent className="p-6 text-center text-sm text-slate-400">
          Select a dependent to view vitals by device.
        </CardContent>
      </Card>
    );
  }

  const devices = data?.devices || [];

  return (
    <Card data-testid="dependent-vitals-card">
      <CardContent className="p-4 space-y-3">
        <div className="flex items-center justify-between">
          <div>
            <h4 className="text-sm font-semibold text-slate-800">
              Vitals by Device
              {dependentName ? (
                <span className="text-slate-400 font-normal"> · {dependentName}</span>
              ) : null}
            </h4>
            <p className="text-[11px] text-slate-400 mt-0.5">
              Last {hours}h · {devices.length} device{devices.length === 1 ? '' : 's'}
            </p>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={fetchData}
            disabled={loading}
            data-testid="dvc-refresh"
          >
            <RefreshCw className={`w-3.5 h-3.5 mr-1 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
        </div>

        {err && (
          <div
            className="rounded border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700"
            data-testid="dvc-error"
          >
            {err}
          </div>
        )}

        {loading && !data && (
          <div className="flex items-center gap-2 text-xs text-slate-400 py-6 justify-center">
            <Loader2 className="w-4 h-4 animate-spin" /> Loading…
          </div>
        )}

        {!loading && !err && devices.length === 0 && (
          <div
            className="text-center py-6 text-xs text-slate-400"
            data-testid="dvc-no-devices"
          >
            No paired devices have reported vitals in the last {hours}h.
          </div>
        )}

        {devices.length > 0 && (
          <div
            className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3"
            data-testid="dvc-devices-grid"
          >
            {devices.map((d) => (
              <DevicePanel key={d.device_id || 'unknown'} device={d} />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default DependentVitalsCard;
