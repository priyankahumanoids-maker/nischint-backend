import React, { useState, useEffect, useCallback } from 'react';
import { Card, CardContent } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Switch } from '../components/ui/switch';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../components/ui/table';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '../components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from '../components/ui/sheet';
import { ScrollArea } from '../components/ui/scroll-area';
import { operatorApi } from '../api';
import { toast } from 'sonner';
import { Loader2, RefreshCw, Settings2, Pencil, History, ChevronDown, ChevronRight, User, RotateCcw } from 'lucide-react';

const severityBadge = (s) => {
  switch (s) {
    case 'high': return <Badge className="bg-red-100 text-red-700" data-testid="severity-high">{s}</Badge>;
    case 'medium': return <Badge className="bg-amber-100 text-amber-700" data-testid="severity-medium">{s}</Badge>;
    default: return <Badge className="bg-slate-100 text-slate-600" data-testid="severity-low">{s}</Badge>;
  }
};

const formatRuleName = (name) => name.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());

const formatThreshold = (ruleName, t) => {
  if (!t) return 'N/A';
  switch (ruleName) {
    case 'low_battery':
      return `Battery < ${t.battery_percent}% (recover +${t.recovery_buffer}%), sustain ${t.sustain_minutes}m`;
    case 'signal_degradation':
      return `Signal < ${t.signal_threshold}dBm (recover +${t.recovery_buffer_dbm}dBm), sustain ${t.sustain_minutes}m`;
    case 'reboot_anomaly':
      return `${t.gap_count} gaps > ${t.gap_minutes}m in ${t.window_minutes}m`;
    default:
      return JSON.stringify(t);
  }
};

const timeAgo = (dateStr) => {
  const diff = (Date.now() - new Date(dateStr).getTime()) / 1000;
  if (diff < 60) return `${Math.floor(diff)}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
};

// ── Diff utilities ──

const DiffValue = ({ label, oldVal, newVal }) => {
  if (oldVal === newVal) return null;
  const oldStr = typeof oldVal === 'object' ? JSON.stringify(oldVal) : String(oldVal);
  const newStr = typeof newVal === 'object' ? JSON.stringify(newVal) : String(newVal);
  return (
    <div className="flex items-center gap-2 text-xs py-0.5">
      <span className="text-slate-500 w-24 shrink-0 font-medium">{label}</span>
      <span className="bg-red-50 text-red-700 px-1.5 py-0.5 rounded line-through font-mono">{oldStr}</span>
      <span className="text-slate-400">→</span>
      <span className="bg-emerald-50 text-emerald-700 px-1.5 py-0.5 rounded font-mono">{newStr}</span>
    </div>
  );
};

const ThresholdDiff = ({ ruleName, oldThreshold, newThreshold }) => {
  if (!oldThreshold || !newThreshold) return null;
  const allKeys = new Set([...Object.keys(oldThreshold), ...Object.keys(newThreshold)]);
  const diffs = [];
  for (const key of allKeys) {
    if (JSON.stringify(oldThreshold[key]) !== JSON.stringify(newThreshold[key])) {
      diffs.push(
        <DiffValue key={key} label={key} oldVal={oldThreshold[key]} newVal={newThreshold[key]} />
      );
    }
  }
  return diffs.length > 0 ? <div className="space-y-0.5">{diffs}</div> : null;
};

const ChangeSummary = ({ entry }) => {
  const { old_config, new_config, rule_name } = entry;
  const changes = [];

  if (old_config.enabled !== new_config.enabled) {
    changes.push(
      <DiffValue key="enabled" label="enabled" oldVal={old_config.enabled ? 'ON' : 'OFF'} newVal={new_config.enabled ? 'ON' : 'OFF'} />
    );
  }
  if (old_config.severity !== new_config.severity) {
    changes.push(
      <DiffValue key="severity" label="severity" oldVal={old_config.severity} newVal={new_config.severity} />
    );
  }
  if (old_config.cooldown_minutes !== new_config.cooldown_minutes) {
    changes.push(
      <DiffValue key="cooldown" label="cooldown" oldVal={`${old_config.cooldown_minutes}m`} newVal={`${new_config.cooldown_minutes}m`} />
    );
  }

  const thresholdDiff = (
    <ThresholdDiff
      ruleName={rule_name}
      oldThreshold={old_config.threshold_json}
      newThreshold={new_config.threshold_json}
    />
  );

  if (changes.length === 0 && !thresholdDiff) {
    return <p className="text-xs text-slate-400 italic">No value changes detected</p>;
  }

  return (
    <div className="space-y-0.5">
      {changes}
      {thresholdDiff}
    </div>
  );
};

import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger } from '../components/ui/alert-dialog';

// ── Audit Entry Card ──

const AuditEntry = ({ entry, isFirst, onRevert, reverting }) => {
  const [expanded, setExpanded] = useState(false);
  const changeBadgeClass = entry.change_type === 'toggle'
    ? 'bg-amber-100 text-amber-700'
    : entry.change_type === 'revert'
    ? 'bg-violet-100 text-violet-700'
    : 'bg-blue-100 text-blue-700';

  return (
    <div className="border border-slate-200 rounded-lg bg-white" data-testid={`audit-entry-${entry.created_at}`}>
      <div
        className="flex items-start gap-3 p-3 cursor-pointer hover:bg-slate-50 transition-colors"
        onClick={() => setExpanded(!expanded)}
        data-testid="audit-entry-header"
      >
        <div className="pt-0.5">
          {expanded
            ? <ChevronDown className="w-4 h-4 text-slate-400" />
            : <ChevronRight className="w-4 h-4 text-slate-400" />
          }
        </div>
        <div className="flex-1 min-w-0 space-y-1.5">
          <div className="flex items-center gap-2 flex-wrap">
            <Badge className={changeBadgeClass} data-testid="audit-change-type">
              {entry.change_type}
            </Badge>
            <span className="text-xs text-slate-500 flex items-center gap-1" data-testid="audit-operator">
              <User className="w-3 h-3" />
              {entry.changed_by_name}
            </span>
            <span className="ml-auto text-xs text-slate-400 tabular-nums" title={new Date(entry.created_at).toLocaleString()} data-testid="audit-timestamp">
              {timeAgo(entry.created_at)}
            </span>
          </div>
          <ChangeSummary entry={entry} />
        </div>
      </div>

      {expanded && (
        <div className="border-t border-slate-100 px-3 pb-3 pt-2 space-y-3" data-testid="audit-entry-detail">
          <div className="text-[10px] text-slate-400 font-mono">{new Date(entry.created_at).toLocaleString()}{entry.ip_address ? ` · IP: ${entry.ip_address}` : ''}</div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <p className="text-[10px] font-semibold text-red-500 uppercase tracking-wider mb-1">Before</p>
              <pre className="text-[11px] bg-red-50 border border-red-100 rounded p-2 text-slate-700 overflow-auto max-h-40 font-mono leading-relaxed" data-testid="audit-old-config">
{JSON.stringify(entry.old_config, null, 2)}</pre>
            </div>
            <div>
              <p className="text-[10px] font-semibold text-emerald-600 uppercase tracking-wider mb-1">After</p>
              <pre className="text-[11px] bg-emerald-50 border border-emerald-100 rounded p-2 text-slate-700 overflow-auto max-h-40 font-mono leading-relaxed" data-testid="audit-new-config">
{JSON.stringify(entry.new_config, null, 2)}</pre>
            </div>
          </div>

          {!isFirst && (
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button
                  variant="outline"
                  size="sm"
                  className="w-full border-slate-300 text-slate-600 hover:bg-slate-100"
                  disabled={reverting}
                  data-testid={`revert-btn-${entry.created_at}`}
                >
                  <RotateCcw className="w-3.5 h-3.5 mr-2" />
                  {reverting ? 'Reverting...' : 'Revert to this version'}
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent data-testid="revert-confirm-dialog">
                <AlertDialogHeader>
                  <AlertDialogTitle>Revert rule configuration?</AlertDialogTitle>
                  <AlertDialogDescription className="space-y-2">
                    <span className="block">This will immediately update the active rule to the state from <strong>{new Date(entry.created_at).toLocaleString()}</strong>.</span>
                    <span className="block text-slate-500">This action will be logged in the audit trail.</span>
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel data-testid="revert-cancel">Cancel</AlertDialogCancel>
                  <AlertDialogAction
                    onClick={(e) => { e.stopPropagation(); onRevert(entry.created_at); }}
                    data-testid="revert-confirm"
                  >
                    Revert
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          )}
          {isFirst && (
            <p className="text-[11px] text-slate-400 italic text-center" data-testid="revert-current-label">This is the current version</p>
          )}
        </div>
      )}
    </div>
  );
};

// ── Threshold Editors ──

const LowBatteryEditor = ({ fields, setField }) => (
  <div className="space-y-4" data-testid="threshold-editor-low_battery">
    <div className="space-y-1">
      <Label>Battery Threshold (%)</Label>
      <Input type="number" min={1} max={100} value={fields.battery_percent}
        onChange={(e) => setField('battery_percent', Number(e.target.value))} data-testid="field-battery_percent" />
    </div>
    <div className="space-y-1">
      <Label>Sustain Window (minutes)</Label>
      <Input type="number" min={1} value={fields.sustain_minutes}
        onChange={(e) => setField('sustain_minutes', Number(e.target.value))} data-testid="field-sustain_minutes" />
    </div>
    <div className="space-y-1">
      <Label>Recovery Buffer (%)</Label>
      <Input type="number" min={0} max={50} value={fields.recovery_buffer}
        onChange={(e) => setField('recovery_buffer', Number(e.target.value))} data-testid="field-recovery_buffer" />
    </div>
  </div>
);

const SignalDegradationEditor = ({ fields, setField }) => (
  <div className="space-y-4" data-testid="threshold-editor-signal_degradation">
    <div className="space-y-1">
      <Label>Signal Threshold (dBm)</Label>
      <Input type="number" max={0} value={fields.signal_threshold}
        onChange={(e) => setField('signal_threshold', Number(e.target.value))} data-testid="field-signal_threshold" />
    </div>
    <div className="space-y-1">
      <Label>Sustain Window (minutes)</Label>
      <Input type="number" min={1} value={fields.sustain_minutes}
        onChange={(e) => setField('sustain_minutes', Number(e.target.value))} data-testid="field-sustain_minutes" />
    </div>
    <div className="space-y-1">
      <Label>Recovery Buffer (dBm)</Label>
      <Input type="number" min={0} value={fields.recovery_buffer_dbm}
        onChange={(e) => setField('recovery_buffer_dbm', Number(e.target.value))} data-testid="field-recovery_buffer_dbm" />
    </div>
  </div>
);

const RebootAnomalyEditor = ({ fields, setField }) => (
  <div className="space-y-4" data-testid="threshold-editor-reboot_anomaly">
    <div className="space-y-1">
      <Label>Gap Duration (minutes)</Label>
      <Input type="number" min={1} value={fields.gap_minutes}
        onChange={(e) => setField('gap_minutes', Number(e.target.value))} data-testid="field-gap_minutes" />
    </div>
    <div className="space-y-1">
      <Label>Gap Count</Label>
      <Input type="number" min={1} value={fields.gap_count}
        onChange={(e) => setField('gap_count', Number(e.target.value))} data-testid="field-gap_count" />
    </div>
    <div className="space-y-1">
      <Label>Detection Window (minutes)</Label>
      <Input type="number" min={1} value={fields.window_minutes}
        onChange={(e) => setField('window_minutes', Number(e.target.value))} data-testid="field-window_minutes" />
    </div>
  </div>
);

const THRESHOLD_EDITORS = {
  low_battery: LowBatteryEditor,
  signal_degradation: SignalDegradationEditor,
  reboot_anomaly: RebootAnomalyEditor,
};

// ── Risk Banner ──

const RiskBanner = ({ result }) => {
  const { matched_devices_count, total_devices_count, simulated_severity } = result;
  const pct = total_devices_count > 0 ? Math.round((matched_devices_count / total_devices_count) * 100) : 0;
  const isSignificant = total_devices_count > 0 && pct >= 20;

  if (matched_devices_count === 0) {
    return (
      <div className="flex items-center gap-2 rounded-md border border-emerald-200 bg-emerald-50 px-4 py-3" data-testid="risk-banner-safe">
        <div className="w-2 h-2 rounded-full bg-emerald-500 shrink-0" />
        <p className="text-sm text-emerald-800">No devices would be affected.</p>
      </div>
    );
  }

  if (simulated_severity === 'medium' || simulated_severity === 'high') {
    return (
      <div className="space-y-2">
        <div className="flex items-center gap-2 rounded-md border border-red-200 bg-red-50 px-4 py-3" data-testid="risk-banner-critical">
          <div className="w-2 h-2 rounded-full bg-red-500 shrink-0" />
          <p className="text-sm text-red-800 font-medium">
            This change would immediately escalate for {matched_devices_count} device{matched_devices_count !== 1 ? 's' : ''}.
          </p>
        </div>
        {isSignificant && (
          <div className="flex items-center gap-2 rounded-md border border-red-300 bg-red-100 px-4 py-2" data-testid="risk-banner-significant">
            <p className="text-xs text-red-700 font-medium">
              This affects {pct}% of all devices — a significant portion of the fleet.
            </p>
          </div>
        )}
      </div>
    );
  }

  // severity = low, matched > 0
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 rounded-md border border-amber-200 bg-amber-50 px-4 py-3" data-testid="risk-banner-warning">
        <div className="w-2 h-2 rounded-full bg-amber-500 shrink-0" />
        <p className="text-sm text-amber-800">
          This change would trigger L1 alerts for {matched_devices_count} device{matched_devices_count !== 1 ? 's' : ''}.
        </p>
      </div>
      {isSignificant && (
        <div className="flex items-center gap-2 rounded-md border border-amber-300 bg-amber-100 px-4 py-2" data-testid="risk-banner-significant">
          <p className="text-xs text-amber-700 font-medium">
            This affects {pct}% of all devices — a significant portion of the fleet.
          </p>
        </div>
      )}
    </div>
  );
};

// ── Main Component ──

export default function HealthRulesPage() {
  const [rules, setRules] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editRule, setEditRule] = useState(null);
  const [editForm, setEditForm] = useState({});
  const [thresholdFields, setThresholdFields] = useState({});
  const [saving, setSaving] = useState(false);

  // Simulation state
  const [previewResult, setPreviewResult] = useState(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState(null);

  // Audit log state
  const [auditRule, setAuditRule] = useState(null);
  const [auditLogs, setAuditLogs] = useState([]);
  const [auditLoading, setAuditLoading] = useState(false);
  const [reverting, setReverting] = useState(false);

  const fetchRules = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await operatorApi.getHealthRules();
      setRules(data);
    } catch {
      toast.error('Failed to load health rules');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchRules(); }, [fetchRules]);

  const handleToggle = async (rule) => {
    const newEnabled = !rule.enabled;
    setRules(prev => prev.map(r => r.rule_name === rule.rule_name ? { ...r, enabled: newEnabled } : r));
    try {
      await operatorApi.toggleHealthRule(rule.rule_name, newEnabled);
      toast.success(`${formatRuleName(rule.rule_name)} ${newEnabled ? 'enabled' : 'disabled'}`);
    } catch {
      setRules(prev => prev.map(r => r.rule_name === rule.rule_name ? { ...r, enabled: rule.enabled } : r));
      toast.error('Failed to toggle rule');
    }
  };

  const openEdit = (rule) => {
    setEditRule(rule);
    setEditForm({ enabled: rule.enabled, severity: rule.severity, cooldown_minutes: rule.cooldown_minutes });
    setThresholdFields({ ...rule.threshold_json });
  };

  const closeEdit = () => { setEditRule(null); setEditForm({ enabled: false, severity: 'low', cooldown_minutes: 1 }); setThresholdFields({}); };

  // Reset preview state when modal closes
  useEffect(() => {
    if (!editRule) {
      setPreviewResult(null);
      setPreviewError(null);
    }
  }, [editRule]);

  const setThresholdField = (key, value) => {
    setThresholdFields(prev => ({ ...prev, [key]: value }));
  };

  const canSave = !saving && editForm.cooldown_minutes >= 1;

  const handlePreview = async () => {
    try {
      setPreviewLoading(true);
      setPreviewError(null);
      setPreviewResult(null);
      const { data } = await operatorApi.simulateHealthRule(editRule.rule_name, {
        enabled: editForm.enabled,
        severity: editForm.severity,
        cooldown_minutes: Number(editForm.cooldown_minutes),
        threshold_json: { ...thresholdFields },
      });
      setPreviewResult(data);
    } catch (err) {
      setPreviewError(err.response?.data?.detail || 'Simulation failed.');
    } finally {
      setPreviewLoading(false);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await operatorApi.updateHealthRule(editRule.rule_name, {
        enabled: editForm.enabled, severity: editForm.severity,
        cooldown_minutes: Number(editForm.cooldown_minutes), threshold_json: { ...thresholdFields },
      });
      toast.success('Rule updated');
      closeEdit();
      fetchRules();
    } catch (err) {
      const detail = err.response?.data?.detail;
      toast.error(typeof detail === 'string' ? detail : 'Failed to save rule');
    } finally { setSaving(false); }
  };

  // Audit log
  const openAuditLog = async (rule) => {
    setAuditRule(rule);
    setAuditLoading(true);
    try {
      const { data } = await operatorApi.getHealthRuleAuditLog(rule.rule_name);
      setAuditLogs(data);
    } catch {
      toast.error('Failed to load audit log');
    } finally {
      setAuditLoading(false);
    }
  };

  const closeAuditLog = () => { setAuditRule(null); setAuditLogs([]); };

  const handleRevert = async (createdAt) => {
    if (!auditRule) return;
    setReverting(true);
    try {
      const { data } = await operatorApi.revertHealthRule(auditRule.rule_name, createdAt);
      toast.success(`Rule reverted to version from ${new Date(data.reverted_to_timestamp).toLocaleString()}.`);
      fetchRules();
      // Re-fetch audit log to show the new revert entry
      const { data: logs } = await operatorApi.getHealthRuleAuditLog(auditRule.rule_name);
      setAuditLogs(logs);
    } catch (err) {
      const detail = err.response?.data?.detail;
      toast.error(typeof detail === 'string' ? detail : 'Revert failed');
    } finally {
      setReverting(false);
    }
  };

  if (loading) {
    return <div className="flex items-center justify-center h-64"><Loader2 className="w-8 h-8 animate-spin text-amber-500" /></div>;
  }

  return (
    <div className="space-y-6" data-testid="op-health-rules-page">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold text-slate-800 flex items-center gap-2">
          <Settings2 className="w-6 h-6 text-amber-500" />
          Device Health Rules
        </h2>
        <Button variant="outline" size="sm" onClick={fetchRules} disabled={loading} data-testid="refresh-health-rules">
          <RefreshCw className={`w-4 h-4 mr-2 ${loading ? 'animate-spin' : ''}`} /> Refresh
        </Button>
      </div>

      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Rule</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Severity</TableHead>
                <TableHead>Cooldown</TableHead>
                <TableHead>Threshold</TableHead>
                <TableHead className="w-28">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rules.length === 0 ? (
                <TableRow><TableCell colSpan={6} className="text-center text-slate-400 py-8">No rules configured</TableCell></TableRow>
              ) : rules.map((rule) => (
                <TableRow key={rule.rule_name} data-testid={`rule-row-${rule.rule_name}`}>
                  <TableCell className="font-medium text-slate-800" data-testid={`rule-name-${rule.rule_name}`}>
                    {formatRuleName(rule.rule_name)}
                  </TableCell>
                  <TableCell>
                    <Switch checked={rule.enabled} onCheckedChange={() => handleToggle(rule)} data-testid={`rule-toggle-${rule.rule_name}`} />
                  </TableCell>
                  <TableCell data-testid={`rule-severity-${rule.rule_name}`}>{severityBadge(rule.severity)}</TableCell>
                  <TableCell className="text-slate-600 tabular-nums" data-testid={`rule-cooldown-${rule.rule_name}`}>{rule.cooldown_minutes}m</TableCell>
                  <TableCell className="text-sm text-slate-500 max-w-xs" data-testid={`rule-threshold-${rule.rule_name}`}>
                    {formatThreshold(rule.rule_name, rule.threshold_json)}
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-1">
                      <Button variant="ghost" size="sm" onClick={() => openEdit(rule)} data-testid={`rule-edit-${rule.rule_name}`}>
                        <Pencil className="w-4 h-4" />
                      </Button>
                      <Button variant="ghost" size="sm" onClick={() => openAuditLog(rule)} data-testid={`rule-history-${rule.rule_name}`}>
                        <History className="w-4 h-4" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* Edit Modal */}
      <Dialog open={!!editRule} onOpenChange={(open) => !open && closeEdit()}>
        <DialogContent className="sm:max-w-xl max-h-[90vh] overflow-y-auto" data-testid="rule-edit-modal">
          <DialogHeader>
            <DialogTitle>Edit Rule: {editRule && formatRuleName(editRule.rule_name)}</DialogTitle>
            <DialogDescription>Modify rule configuration and preview impact before saving.</DialogDescription>
          </DialogHeader>
          <div className="space-y-5 py-4">
            <div className="flex items-center justify-between">
              <Label htmlFor="edit-enabled">Enabled</Label>
              <Switch id="edit-enabled" checked={editForm.enabled} onCheckedChange={(val) => setEditForm(f => ({ ...f, enabled: val }))} data-testid="edit-rule-enabled" />
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit-severity">Severity</Label>
              <Select value={editForm.severity} onValueChange={(val) => setEditForm(f => ({ ...f, severity: val }))}>
                <SelectTrigger data-testid="edit-rule-severity"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="low">Low</SelectItem>
                  <SelectItem value="medium">Medium</SelectItem>
                  <SelectItem value="high">High</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit-cooldown">Cooldown (minutes)</Label>
              <Input id="edit-cooldown" type="number" min={1} value={editForm.cooldown_minutes}
                onChange={(e) => setEditForm(f => ({ ...f, cooldown_minutes: parseInt(e.target.value) || 0 }))} data-testid="edit-rule-cooldown" />
              {editForm.cooldown_minutes < 1 && <p className="text-xs text-red-500">Must be at least 1 minute</p>}
            </div>
            {editRule && THRESHOLD_EDITORS[editRule.rule_name] && (
              <div className="space-y-2">
                <Label>Threshold Configuration</Label>
                {React.createElement(THRESHOLD_EDITORS[editRule.rule_name], {
                  fields: thresholdFields,
                  setField: setThresholdField,
                })}
              </div>
            )}
          </div>

          {/* Impact Summary Panel */}
          {previewResult && (
            <div className="mt-4 space-y-3" data-testid="impact-summary-panel">
              {/* Risk Banner */}
              <RiskBanner result={previewResult} />

              <div className="p-4 border rounded-lg bg-muted/40">
                <h4 className="font-semibold mb-2">Impact Summary</h4>
                <div className="text-sm space-y-1">
                  <p>Matched Devices: <strong data-testid="sim-matched-count">{previewResult.matched_devices_count}</strong>{previewResult.total_devices_count > 0 && <span className="text-muted-foreground"> / {previewResult.total_devices_count} total</span>}</p>
                  <p>Would Escalate: <strong data-testid="sim-would-escalate">{previewResult.would_escalate ? 'Yes' : 'No'}</strong></p>
                  <p>Severity: <strong data-testid="sim-severity">{previewResult.simulated_severity}</strong></p>
                  <p>Evaluation Window: <strong data-testid="sim-window">{previewResult.evaluation_window_minutes} minutes</strong></p>
                </div>
                {previewResult.matched_devices?.length > 0 && (
                  <ul className="mt-3 text-sm space-y-1" data-testid="sim-device-list">
                    {previewResult.matched_devices.slice(0, 10).map((d, i) => (
                      <li key={i} data-testid={`sim-device-${i}`}>
                        {d.device_identifier} — {d.senior_name}
                      </li>
                    ))}
                    {previewResult.matched_devices_count > 10 && (
                      <li className="text-muted-foreground italic" data-testid="sim-more-devices">
                        + {previewResult.matched_devices_count - 10} more devices
                      </li>
                    )}
                  </ul>
                )}
              </div>
            </div>
          )}

          {/* Preview Error */}
          {previewError && (
            <div className="mt-4 text-sm text-red-600" data-testid="sim-error">{previewError}</div>
          )}

          <DialogFooter>
            <Button variant="outline" onClick={closeEdit} data-testid="edit-rule-cancel">Cancel</Button>
            <Button variant="secondary" onClick={handlePreview} disabled={previewLoading} data-testid="preview-impact-btn">
              {previewLoading ? 'Previewing...' : 'Preview Impact'}
            </Button>
            <Button onClick={handleSave} disabled={!canSave} data-testid="edit-rule-save">
              {saving ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : null}
              Save Changes
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Audit Log Drawer */}
      <Sheet open={!!auditRule} onOpenChange={(open) => !open && closeAuditLog()}>
        <SheetContent className="w-full sm:max-w-lg p-0 flex flex-col" data-testid="audit-log-drawer">
          <SheetHeader className="px-6 pt-6 pb-4 border-b border-slate-100 shrink-0">
            <SheetTitle className="flex items-center gap-2 text-lg">
              <History className="w-5 h-5 text-amber-500" />
              Change History
            </SheetTitle>
            {auditRule && (
              <SheetDescription>{formatRuleName(auditRule.rule_name)}</SheetDescription>
            )}
          </SheetHeader>
          <ScrollArea className="flex-1 px-6 py-4">
            {auditLoading ? (
              <div className="flex items-center justify-center h-32">
                <Loader2 className="w-6 h-6 animate-spin text-amber-500" />
              </div>
            ) : auditLogs.length === 0 ? (
              <div className="text-center py-12" data-testid="audit-empty">
                <History className="w-10 h-10 text-slate-200 mx-auto mb-3" />
                <p className="text-slate-400 text-sm">No changes recorded yet</p>
              </div>
            ) : (
              <div className="space-y-3" data-testid="audit-log-list">
                {auditLogs.map((entry, i) => (
                  <AuditEntry
                    key={`${entry.created_at}-${i}`}
                    entry={entry}
                    isFirst={i === 0}
                    onRevert={handleRevert}
                    reverting={reverting}
                  />
                ))}
              </div>
            )}
          </ScrollArea>
        </SheetContent>
      </Sheet>
    </div>
  );
}
