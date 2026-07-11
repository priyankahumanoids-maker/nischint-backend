import React, { useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../../components/ui/card';
import { Badge } from '../../components/ui/badge';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../../components/ui/table';
import { AlertTriangle } from 'lucide-react';

export function CompareResultsPanel({ result }) {
  const [activeDeviceTab, setActiveDeviceTab] = useState('newly_flagged');

  const DEVICE_TABS = [
    { key: 'newly_flagged', label: 'Newly Flagged' },
    { key: 'no_longer_flagged', label: 'No Longer Flagged' },
    { key: 'tier_upgraded', label: 'Tier Upgraded' },
    { key: 'tier_downgraded', label: 'Tier Downgraded' },
  ];

  const getRiskBanner = () => {
    if (!result) return null;
    const d = result.delta;
    const ts = d.tier_shift;
    if (ts.L3 > 0 || ts.L2 > 2) {
      return { type: 'red', msg: 'Config B increases high-severity instability incidents.' };
    }
    if (d.instability_diff < 0 && ts.L3 > 0) {
      return { type: 'amber', msg: 'Noise reduced but severe incidents increased.' };
    }
    if (ts.L1 <= 0 && ts.L2 <= 0 && ts.L3 <= 0 && d.anomalies_diff <= 0) {
      return { type: 'green', msg: 'Config B reduces instability sensitivity.' };
    }
    return null;
  };

  const riskBanner = getRiskBanner();

  return (
    <div className="space-y-4" data-testid="compare-results-panel">
      {/* Risk Banner */}
      {riskBanner && (
        <div className={`rounded-lg px-4 py-3 flex items-center gap-3 border ${
          riskBanner.type === 'red' ? 'bg-red-50 border-red-200 text-red-800' :
          riskBanner.type === 'amber' ? 'bg-amber-50 border-amber-200 text-amber-800' :
          'bg-emerald-50 border-emerald-200 text-emerald-800'
        }`} data-testid="compare-risk-banner">
          <AlertTriangle className="w-5 h-5 shrink-0" />
          <p className="text-sm font-medium">{riskBanner.msg}</p>
        </div>
      )}

      {/* Delta KPIs */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3" data-testid="compare-delta-kpis">
        <DeltaCard label="Anomalies" delta={result.delta.anomalies_diff}
          a={result.summary.config_a.anomalies} b={result.summary.config_b.anomalies} testId="delta-anomalies" />
        <DeltaCard label="Instability" delta={result.delta.instability_diff}
          a={result.summary.config_a.instability_incidents} b={result.summary.config_b.instability_incidents} testId="delta-instability" />
        <DeltaCard label="L1" delta={result.delta.tier_shift.L1}
          a={result.summary.config_a.tier_counts.L1} b={result.summary.config_b.tier_counts.L1} tier="L1" testId="delta-l1" />
        <DeltaCard label="L2" delta={result.delta.tier_shift.L2}
          a={result.summary.config_a.tier_counts.L2} b={result.summary.config_b.tier_counts.L2} tier="L2" testId="delta-l2" />
        <DeltaCard label="L3" delta={result.delta.tier_shift.L3}
          a={result.summary.config_a.tier_counts.L3} b={result.summary.config_b.tier_counts.L3} tier="L3" testId="delta-l3" />
      </div>

      {/* Tier Shift Visualization */}
      <Card data-testid="compare-tier-chart">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-semibold text-slate-600">Tier Distribution Shift</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            <TierCompareBar label="Config A" tiers={result.summary.config_a.tier_counts} total={result.summary.config_a.anomalies} color="blue" />
            <TierCompareBar label="Config B" tiers={result.summary.config_b.tier_counts} total={result.summary.config_b.anomalies} color="teal" />
          </div>
        </CardContent>
      </Card>

      {/* Device Changes */}
      <Card data-testid="compare-device-changes">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-semibold text-slate-600">Device-Level Changes</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <div className="flex border-b border-slate-100 px-4" data-testid="compare-device-tabs">
            {DEVICE_TABS.map(t => {
              const count = (result.device_changes?.[t.key] || []).length;
              return (
                <button key={t.key} onClick={() => setActiveDeviceTab(t.key)}
                  className={`px-3 py-2.5 text-xs font-medium border-b-2 transition-colors ${
                    activeDeviceTab === t.key ? 'border-teal-500 text-teal-700' : 'border-transparent text-slate-400 hover:text-slate-600'
                  }`} data-testid={`compare-dtab-${t.key}`}>
                  {t.label} <Badge variant="outline" className="ml-1 text-[10px]">{count}</Badge>
                </button>
              );
            })}
          </div>
          <DeviceChangeTable items={result.device_changes?.[activeDeviceTab] || []} />
        </CardContent>
      </Card>
    </div>
  );
}

function DeltaCard({ label, delta, a, b, tier, testId }) {
  const isIncrease = delta > 0;
  const isDecrease = delta < 0;
  const tierColors = { L1: 'amber', L2: 'orange', L3: 'red' };
  const bgClass = {
    red: 'bg-red-50 border-red-100', amber: 'bg-amber-50 border-amber-100',
    orange: 'bg-orange-50 border-orange-100', emerald: 'bg-emerald-50 border-emerald-100',
    slate: 'bg-slate-50 border-slate-100',
  }[isIncrease && !tier ? 'red' : isDecrease && !tier ? 'emerald' : tier ? tierColors[tier] : 'slate'];
  const textClass = {
    red: 'text-red-700', amber: 'text-amber-700', orange: 'text-orange-700',
    emerald: 'text-emerald-700', slate: 'text-slate-600',
  }[isIncrease && !tier ? 'red' : isDecrease && !tier ? 'emerald' : tier ? tierColors[tier] : 'slate'];

  return (
    <div className={`p-3 rounded-lg border ${bgClass}`} data-testid={testId}>
      <p className="text-[10px] uppercase tracking-wide text-slate-400 mb-1">{label}</p>
      <div className="flex items-baseline gap-2">
        <span className={`text-2xl font-bold ${textClass}`}>
          {delta > 0 ? '+' : ''}{delta}
        </span>
        <span className="text-[10px] text-slate-400">{a} &rarr; {b}</span>
      </div>
    </div>
  );
}

function TierCompareBar({ label, tiers, total, color }) {
  const maxBar = Math.max(total, 1);
  const l1p = (tiers.L1 / maxBar * 100) || 0;
  const l2p = (tiers.L2 / maxBar * 100) || 0;
  const l3p = (tiers.L3 / maxBar * 100) || 0;
  const borderCol = color === 'blue' ? 'text-blue-600' : 'text-teal-600';

  return (
    <div className="flex items-center gap-3" data-testid={`tier-bar-${color}`}>
      <span className={`text-xs font-mono w-16 ${borderCol}`}>{label}</span>
      <div className="flex-1 flex h-5 rounded overflow-hidden bg-slate-100">
        {l1p > 0 && <div className="bg-amber-400" style={{ width: `${l1p}%` }} />}
        {l2p > 0 && <div className="bg-orange-400" style={{ width: `${l2p}%` }} />}
        {l3p > 0 && <div className="bg-red-500" style={{ width: `${l3p}%` }} />}
      </div>
      <span className="text-xs text-slate-400 w-12 text-right">{tiers.L1}/{tiers.L2}/{tiers.L3}</span>
    </div>
  );
}

function DeviceChangeTable({ items }) {
  if (!items.length) {
    return (
      <div className="flex items-center justify-center py-10 text-sm text-slate-400" data-testid="compare-devices-empty">
        No devices in this category
      </div>
    );
  }
  return (
    <Table data-testid="compare-devices-table">
      <TableHeader>
        <TableRow className="bg-slate-50">
          <TableHead className="text-[10px] uppercase tracking-wider font-semibold">Device</TableHead>
          <TableHead className="text-[10px] uppercase tracking-wider font-semibold text-center">Score A</TableHead>
          <TableHead className="text-[10px] uppercase tracking-wider font-semibold text-center">Score B</TableHead>
          <TableHead className="text-[10px] uppercase tracking-wider font-semibold text-center">Tier A</TableHead>
          <TableHead className="text-[10px] uppercase tracking-wider font-semibold text-center">Tier B</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {items.map((d, i) => (
          <TableRow key={i} data-testid={`compare-device-row-${i}`}>
            <TableCell className="font-mono text-xs text-slate-700">{d.device_identifier}</TableCell>
            <TableCell className="text-center text-sm">{d.score_a}</TableCell>
            <TableCell className="text-center text-sm font-medium">{d.score_b}</TableCell>
            <TableCell className="text-center">
              {d.tier_a ? <Badge variant="outline" className="text-[10px]">{d.tier_a}</Badge> : <span className="text-slate-300">&mdash;</span>}
            </TableCell>
            <TableCell className="text-center">
              {d.tier_b ? <Badge variant="outline" className="text-[10px]">{d.tier_b}</Badge> : <span className="text-slate-300">&mdash;</span>}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
