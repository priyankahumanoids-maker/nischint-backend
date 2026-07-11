import React from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../../components/ui/card';
import { Button } from '../../components/ui/button';
import { AlertTriangle, Loader2 } from 'lucide-react';

export function CompareApplyDialog({ open, onClose, confirmChecked, setConfirmChecked, applying, onApply }) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" data-testid="compare-confirm-overlay">
      <Card className="w-full max-w-md mx-4" data-testid="compare-confirm-dialog">
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2 text-red-700">
            <AlertTriangle className="w-5 h-5" /> Apply Config B to Production
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-slate-600">
            You are about to update the <code className="bg-slate-100 px-1 rounded text-xs">combined_anomaly</code> rule.
            This will immediately affect production escalation behavior. This action will be logged.
          </p>
          <div className="rounded-lg bg-red-50 border border-red-100 px-3 py-2">
            <p className="text-xs text-red-700 font-medium">
              This change cannot be undone from this UI. Use the Health Rules governance page to revert if needed.
            </p>
          </div>
          <div className="flex items-start gap-2">
            <input type="checkbox" id="confirm-check" checked={confirmChecked}
              onChange={e => setConfirmChecked(e.target.checked)}
              className="mt-1" data-testid="compare-confirm-checkbox" />
            <label htmlFor="confirm-check" className="text-xs text-slate-600 cursor-pointer">
              I understand this affects production safety thresholds and have reviewed the comparison results
            </label>
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={onClose} data-testid="compare-confirm-cancel">
              Cancel
            </Button>
            <Button variant="destructive" disabled={!confirmChecked || applying}
              onClick={onApply} data-testid="compare-confirm-apply">
              {applying ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : null}
              Confirm Apply
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
