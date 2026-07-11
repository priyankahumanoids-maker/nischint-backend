import React from 'react';
import { Card, CardContent, CardHeader } from '../../components/ui/card';
import { Button } from '../../components/ui/button';
import { Badge } from '../../components/ui/badge';
import { Input } from '../../components/ui/input';
import { Label } from '../../components/ui/label';
import { Separator } from '../../components/ui/separator';
import { Zap, RotateCcw, TrendingUp, Shield } from 'lucide-react';

const PRESETS = {
  conservative: {
    label: 'Conservative',
    icon: Shield,
    desc: 'Fewer alerts, higher thresholds',
    config: {
      weight_battery: 0.5, weight_signal: 0.3, weight_behavior: 0.2,
      trigger_threshold: 70, correlation_bonus: 5, persistence_minutes: 20,
      recovery_minutes: 20, recovery_buffer: 10, min_clear_cycles: 3,
      instability_cooldown_minutes: 45,
      escalation_tiers: { '70-85': 'L1', '85-95': 'L2', '95-100': 'L3' },
    },
  },
  balanced: {
    label: 'Balanced',
    icon: Zap,
    desc: 'Default recommended settings',
    config: {
      weight_battery: 0.5, weight_signal: 0.3, weight_behavior: 0.2,
      trigger_threshold: 60, correlation_bonus: 10, persistence_minutes: 15,
      recovery_minutes: 15, recovery_buffer: 5, min_clear_cycles: 2,
      instability_cooldown_minutes: 30,
      escalation_tiers: { '60-75': 'L1', '75-90': 'L2', '90-100': 'L3' },
    },
  },
  aggressive: {
    label: 'Aggressive',
    icon: TrendingUp,
    desc: 'More sensitive detection',
    config: {
      weight_battery: 0.4, weight_signal: 0.3, weight_behavior: 0.3,
      trigger_threshold: 50, correlation_bonus: 15, persistence_minutes: 10,
      recovery_minutes: 10, recovery_buffer: 3, min_clear_cycles: 1,
      instability_cooldown_minutes: 15,
      escalation_tiers: { '50-65': 'L1', '65-80': 'L2', '80-100': 'L3' },
    },
  },
};

export function CompareConfigCard({ label, sublabel, config, setConfig, accent, onLoadProd, testPrefix, showPresets }) {
  const update = (key, val) => setConfig(prev => ({ ...prev, [key]: val }));
  const borderColor = accent === 'blue' ? 'border-blue-200' : 'border-teal-200';
  const labelColor = accent === 'blue' ? 'text-blue-700 bg-blue-50' : 'text-teal-700 bg-teal-50';
  const wSum = Math.round((config.weight_battery + config.weight_signal + (config.weight_behavior || 0)) * 100) / 100;
  const wValid = Math.abs(wSum - 1.0) <= 0.01;

  const updateTier = (tierKey, field, value) => {
    const tiers = { ...config.escalation_tiers };
    const entries = Object.entries(tiers);
    const idx = entries.findIndex(([, v]) => v === tierKey);
    if (idx === -1) return;
    const [rangeStr] = entries[idx];
    const [lo, hi] = rangeStr.split('-').map(Number);
    const newLo = field === 'lo' ? value : lo;
    const newHi = field === 'hi' ? value : hi;
    const newTiers = {};
    entries.forEach(([rng, tier]) => {
      if (tier === tierKey) {
        newTiers[`${newLo}-${newHi}`] = tier;
      } else {
        newTiers[rng] = tier;
      }
    });
    update('escalation_tiers', newTiers);
  };

  const parseTiers = () => {
    const tiers = config.escalation_tiers || {};
    const result = { L1: { lo: 60, hi: 75 }, L2: { lo: 75, hi: 90 }, L3: { lo: 90, hi: 100 } };
    Object.entries(tiers).forEach(([rng, tier]) => {
      const [lo, hi] = rng.split('-').map(Number);
      if (result[tier]) {
        result[tier] = { lo, hi };
      }
    });
    return result;
  };

  const tierValues = parseTiers();

  const applyPreset = (presetKey) => {
    setConfig({ ...PRESETS[presetKey].config });
  };

  return (
    <Card className={`border-2 ${borderColor}`} data-testid={`${testPrefix}-card`}>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Badge className={`text-xs ${labelColor}`}>{label}</Badge>
            <span className="text-[10px] text-slate-400">{sublabel}</span>
          </div>
          {onLoadProd && (
            <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={onLoadProd} data-testid={`${testPrefix}-load-prod`}>
              <RotateCcw className="w-3 h-3 mr-1" /> Load Production
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* Presets for Config B */}
        {showPresets && (
          <div className="space-y-1.5" data-testid={`${testPrefix}-presets`}>
            <Label className="text-[10px] uppercase tracking-wide text-slate-400">Quick Presets</Label>
            <div className="flex gap-2">
              {Object.entries(PRESETS).map(([key, preset]) => {
                const Icon = preset.icon;
                return (
                  <Button
                    key={key}
                    variant="outline"
                    size="sm"
                    className="h-8 text-xs flex-1"
                    onClick={() => applyPreset(key)}
                    data-testid={`${testPrefix}-preset-${key}`}
                  >
                    <Icon className="w-3 h-3 mr-1" />
                    {preset.label}
                  </Button>
                );
              })}
            </div>
          </div>
        )}

        {/* Weights */}
        <div>
          <Label className="text-[10px] uppercase tracking-wide text-slate-400 mb-1.5 block">Metric Weights</Label>
          <div className="grid grid-cols-3 gap-3">
            <div>
              <Label className="text-[10px] text-slate-500">Battery</Label>
              <Input type="number" step="0.1" min="0" max="1" value={config.weight_battery}
                onChange={e => update('weight_battery', parseFloat(e.target.value) || 0)}
                className="h-8 text-sm" data-testid={`${testPrefix}-weight-bat`} />
            </div>
            <div>
              <Label className="text-[10px] text-slate-500">Signal</Label>
              <Input type="number" step="0.1" min="0" max="1" value={config.weight_signal}
                onChange={e => update('weight_signal', parseFloat(e.target.value) || 0)}
                className="h-8 text-sm" data-testid={`${testPrefix}-weight-sig`} />
            </div>
            <div>
              <Label className="text-[10px] text-slate-500">Behavior</Label>
              <Input type="number" step="0.1" min="0" max="1" value={config.weight_behavior ?? 0}
                onChange={e => update('weight_behavior', parseFloat(e.target.value) || 0)}
                className="h-8 text-sm" data-testid={`${testPrefix}-weight-beh`} />
            </div>
          </div>
          {!wValid && (
            <p className="text-[10px] text-red-500 font-medium mt-1" data-testid={`${testPrefix}-weight-error`}>
              Weights sum to {wSum} (must equal 1.0)
            </p>
          )}
        </div>

        {/* Detection Parameters */}
        <div>
          <Label className="text-[10px] uppercase tracking-wide text-slate-400 mb-1.5 block">Detection</Label>
          <div className="grid grid-cols-3 gap-3">
            <div>
              <Label className="text-[10px] text-slate-500">Threshold</Label>
              <Input type="number" min="0" max="100" value={config.trigger_threshold}
                onChange={e => update('trigger_threshold', parseFloat(e.target.value) || 0)}
                className="h-8 text-sm" data-testid={`${testPrefix}-threshold`} />
            </div>
            <div>
              <Label className="text-[10px] text-slate-500">Corr. Bonus</Label>
              <Input type="number" min="0" max="50" value={config.correlation_bonus}
                onChange={e => update('correlation_bonus', parseFloat(e.target.value) || 0)}
                className="h-8 text-sm" data-testid={`${testPrefix}-bonus`} />
            </div>
            <div>
              <Label className="text-[10px] text-slate-500">Persist. (min)</Label>
              <Input type="number" min="1" value={config.persistence_minutes}
                onChange={e => update('persistence_minutes', parseInt(e.target.value) || 1)}
                className="h-8 text-sm" data-testid={`${testPrefix}-persist`} />
            </div>
          </div>
        </div>

        <Separator className="my-1" />

        {/* Recovery Parameters */}
        <div>
          <Label className="text-[10px] uppercase tracking-wide text-slate-400 mb-1.5 block">Recovery & Cooldown</Label>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label className="text-[10px] text-slate-500">Recovery (min)</Label>
              <Input type="number" min="1" value={config.recovery_minutes}
                onChange={e => update('recovery_minutes', parseInt(e.target.value) || 1)}
                className="h-8 text-sm" data-testid={`${testPrefix}-recovery-min`} />
            </div>
            <div>
              <Label className="text-[10px] text-slate-500">Recovery Buffer</Label>
              <Input type="number" min="0" max="50" value={config.recovery_buffer}
                onChange={e => update('recovery_buffer', parseInt(e.target.value) || 0)}
                className="h-8 text-sm" data-testid={`${testPrefix}-recovery-buf`} />
            </div>
            <div>
              <Label className="text-[10px] text-slate-500">Clear Cycles</Label>
              <Input type="number" min="1" value={config.min_clear_cycles}
                onChange={e => update('min_clear_cycles', parseInt(e.target.value) || 1)}
                className="h-8 text-sm" data-testid={`${testPrefix}-clear-cycles`} />
            </div>
            <div>
              <Label className="text-[10px] text-slate-500">Cooldown (min)</Label>
              <Input type="number" min="1" value={config.instability_cooldown_minutes}
                onChange={e => update('instability_cooldown_minutes', parseInt(e.target.value) || 1)}
                className="h-8 text-sm" data-testid={`${testPrefix}-cooldown`} />
            </div>
          </div>
        </div>

        <Separator className="my-1" />

        {/* Escalation Tiers Editor */}
        <div data-testid={`${testPrefix}-tiers-editor`}>
          <Label className="text-[10px] uppercase tracking-wide text-slate-400 mb-1.5 block">Escalation Tiers</Label>
          <div className="space-y-2">
            {['L1', 'L2', 'L3'].map((tier) => {
              const tierColor = tier === 'L1' ? 'bg-amber-50 border-amber-200 text-amber-700'
                : tier === 'L2' ? 'bg-orange-50 border-orange-200 text-orange-700'
                : 'bg-red-50 border-red-200 text-red-700';
              return (
                <div key={tier} className="flex items-center gap-2" data-testid={`${testPrefix}-tier-${tier}`}>
                  <Badge variant="outline" className={`text-[10px] w-8 justify-center ${tierColor}`}>{tier}</Badge>
                  <Input
                    type="number" min="0" max="100"
                    value={tierValues[tier].lo}
                    onChange={e => updateTier(tier, 'lo', parseInt(e.target.value) || 0)}
                    className="h-7 text-xs w-16 text-center"
                    data-testid={`${testPrefix}-tier-${tier}-lo`}
                  />
                  <span className="text-xs text-slate-400">to</span>
                  <Input
                    type="number" min="0" max="100"
                    value={tierValues[tier].hi}
                    onChange={e => updateTier(tier, 'hi', parseInt(e.target.value) || 0)}
                    className="h-7 text-xs w-16 text-center"
                    data-testid={`${testPrefix}-tier-${tier}-hi`}
                  />
                </div>
              );
            })}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
