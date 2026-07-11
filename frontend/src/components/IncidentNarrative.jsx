import React, { useState, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Badge } from './ui/badge';
import { Button } from './ui/button';
import { operatorApi } from '../api';
import { toast } from 'sonner';
import {
  Brain, Sparkles, Loader2, RefreshCw, AlertTriangle,
  CheckCircle, Clock, Shield, ChevronDown, ChevronUp
} from 'lucide-react';

const confidenceColor = (c) => {
  if (c >= 0.8) return 'bg-emerald-100 text-emerald-700 border-emerald-200';
  if (c >= 0.6) return 'bg-blue-100 text-blue-700 border-blue-200';
  if (c >= 0.4) return 'bg-amber-100 text-amber-700 border-amber-200';
  return 'bg-red-100 text-red-700 border-red-200';
};

const priorityIcon = (p) => {
  if (p === 1) return <AlertTriangle className="w-3.5 h-3.5 text-red-500" />;
  if (p === 2) return <Clock className="w-3.5 h-3.5 text-amber-500" />;
  return <CheckCircle className="w-3.5 h-3.5 text-slate-400" />;
};

const ownerBadge = (o) => {
  const styles = {
    operator: 'bg-purple-50 text-purple-700 border-purple-200',
    guardian: 'bg-blue-50 text-blue-700 border-blue-200',
    system: 'bg-slate-50 text-slate-600 border-slate-200',
  };
  return styles[o] || styles.system;
};

export const IncidentNarrative = ({ incidentId }) => {
  const [status, setStatus] = useState(null);
  const [narrative, setNarrative] = useState(null);
  const [generating, setGenerating] = useState(false);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [history, setHistory] = useState([]);

  useEffect(() => {
    checkStatus();
  }, [incidentId]);

  const checkStatus = async () => {
    setLoading(true);
    try {
      const { data } = await operatorApi.getNarrativeStatus(incidentId);
      setStatus(data);
      if (data.has_narrative) {
        const { data: narratives } = await operatorApi.getNarratives(incidentId, 1);
        if (narratives.length > 0) {
          setNarrative(narratives[0]);
          setExpanded(true);
        }
      }
    } catch {
      // silently fail - narrative is optional
    } finally {
      setLoading(false);
    }
  };

  const handleGenerate = async () => {
    setGenerating(true);
    try {
      const { data } = await operatorApi.generateNarrative(incidentId);
      setNarrative(data);
      setExpanded(true);
      setStatus(prev => ({ ...prev, has_narrative: true, is_stale: false }));
      toast.success(data.cached ? 'Narrative is already up-to-date' : `Narrative v${data.narrative_version} generated`);
    } catch (err) {
      toast.error('Failed to generate narrative');
    } finally {
      setGenerating(false);
    }
  };

  const loadHistory = async () => {
    try {
      const { data } = await operatorApi.getNarratives(incidentId);
      setHistory(data);
      setShowHistory(true);
    } catch {
      toast.error('Failed to load narrative history');
    }
  };

  const n = narrative?.narrative || narrative?.narrative_json || {};

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-sm text-slate-400 py-3">
        <Loader2 className="w-4 h-4 animate-spin" /> Checking AI narrative...
      </div>
    );
  }

  return (
    <div className="mt-3" data-testid={`narrative-section-${incidentId}`}>
      <div className="flex items-center justify-between mb-2">
        <h4 className="text-sm font-semibold text-slate-700 flex items-center gap-1.5">
          <Brain className="w-3.5 h-3.5 text-violet-500" />
          AI Incident Summary
          {status?.has_narrative && !status?.is_stale && (
            <Badge className="bg-emerald-50 text-emerald-600 border border-emerald-200 text-[10px] ml-1">
              Up-to-date
            </Badge>
          )}
          {status?.is_stale && status?.has_narrative && (
            <Badge className="bg-amber-50 text-amber-600 border border-amber-200 text-[10px] ml-1">
              Stale
            </Badge>
          )}
        </h4>
        <div className="flex items-center gap-1.5">
          {narrative && (
            <Button
              variant="ghost"
              size="sm"
              className="h-7 px-2 text-xs text-slate-500"
              onClick={() => setExpanded(!expanded)}
              data-testid={`narrative-toggle-${incidentId}`}
            >
              {expanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
            </Button>
          )}
          <Button
            size="sm"
            variant={status?.has_narrative ? "outline" : "default"}
            className={`h-7 px-3 text-xs ${!status?.has_narrative ? 'bg-violet-600 hover:bg-violet-700 text-white' : ''}`}
            onClick={handleGenerate}
            disabled={generating}
            data-testid={`narrative-generate-${incidentId}`}
          >
            {generating ? (
              <><Loader2 className="w-3 h-3 animate-spin mr-1" /> Generating...</>
            ) : status?.has_narrative ? (
              <><RefreshCw className="w-3 h-3 mr-1" /> Regenerate</>
            ) : (
              <><Sparkles className="w-3 h-3 mr-1" /> Generate AI Summary</>
            )}
          </Button>
        </div>
      </div>

      {expanded && narrative && (
        <div className="bg-gradient-to-br from-violet-50/80 via-white to-indigo-50/50 rounded-lg border border-violet-100 p-4 space-y-3" data-testid={`narrative-content-${incidentId}`}>
          {/* Title + Confidence */}
          <div className="flex items-start justify-between gap-3">
            <div>
              <h5 className="font-semibold text-slate-800 text-sm">{n.title}</h5>
              <p className="text-xs text-slate-500 mt-0.5">{n.one_line_summary}</p>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <Badge className={`${confidenceColor(n.confidence || 0)} text-[10px] border`}>
                {Math.round((n.confidence || 0) * 100)}% confidence
              </Badge>
              <Badge className="bg-slate-50 text-slate-500 border border-slate-200 text-[10px]">
                {narrative.generated_by === 'ai' ? 'GPT-5.2' : 'Template'}
              </Badge>
            </div>
          </div>

          {/* Safety Note */}
          {n.safety_note && (
            <div className="flex items-start gap-2 px-3 py-2 bg-amber-50 border border-amber-200 rounded-md text-xs text-amber-700">
              <Shield className="w-3.5 h-3.5 mt-0.5 shrink-0" />
              {n.safety_note}
            </div>
          )}

          {/* What Happened */}
          {n.what_happened && n.what_happened.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-slate-600 mb-1">What Happened</p>
              <ul className="space-y-0.5">
                {n.what_happened.map((item, i) => (
                  <li key={i} className="text-xs text-slate-600 pl-3 relative before:content-[''] before:absolute before:left-0 before:top-[7px] before:w-1.5 before:h-1.5 before:rounded-full before:bg-violet-300">
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Why It Happened */}
          {n.why_it_happened && n.why_it_happened.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-slate-600 mb-1">Contributing Factors</p>
              <ul className="space-y-0.5">
                {n.why_it_happened.map((item, i) => (
                  <li key={i} className="text-xs text-slate-600 pl-3 relative before:content-[''] before:absolute before:left-0 before:top-[7px] before:w-1.5 before:h-1.5 before:rounded-full before:bg-amber-300">
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Evidence */}
          {n.evidence && n.evidence.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-slate-600 mb-1">Evidence Timeline</p>
              <div className="space-y-1">
                {n.evidence.map((e, i) => (
                  <div key={i} className="flex items-start gap-2 text-xs">
                    <span className="text-slate-400 font-mono text-[10px] shrink-0 w-[140px]">
                      {e.timestamp ? new Date(e.timestamp).toLocaleString() : '-'}
                    </span>
                    <span className="text-slate-600">{e.fact}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Recommended Actions */}
          {n.recommended_actions && n.recommended_actions.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-slate-600 mb-1">Recommended Actions</p>
              <div className="space-y-1">
                {n.recommended_actions.map((a, i) => (
                  <div key={i} className="flex items-center gap-2 text-xs px-2 py-1.5 bg-white/70 rounded border border-slate-100">
                    {priorityIcon(a.priority)}
                    <span className="text-slate-700 flex-1">{a.action}</span>
                    <Badge className={`${ownerBadge(a.owner)} text-[10px] border`}>{a.owner}</Badge>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Footer: Version + History */}
          <div className="flex items-center justify-between pt-2 border-t border-violet-100">
            <span className="text-[10px] text-slate-400">
              v{narrative.narrative_version || 1} - {narrative.created_at ? new Date(narrative.created_at).toLocaleString() : ''}
            </span>
            {status?.has_narrative && (
              <Button
                variant="ghost"
                size="sm"
                className="h-6 px-2 text-[10px] text-violet-500 hover:text-violet-700"
                onClick={loadHistory}
                data-testid={`narrative-history-${incidentId}`}
              >
                View History
              </Button>
            )}
          </div>

          {/* History Panel */}
          {showHistory && history.length > 0 && (
            <div className="border-t border-violet-100 pt-2">
              <div className="flex items-center justify-between mb-1.5">
                <p className="text-xs font-semibold text-slate-600">Narrative History ({history.length})</p>
                <Button variant="ghost" size="sm" className="h-6 px-2 text-[10px]" onClick={() => setShowHistory(false)}>
                  Close
                </Button>
              </div>
              <div className="space-y-1.5 max-h-40 overflow-y-auto">
                {history.map((h) => (
                  <div
                    key={h.id}
                    className={`flex items-center gap-2 text-xs px-2 py-1.5 rounded border cursor-pointer transition-colors ${
                      narrative.id === h.id ? 'bg-violet-50 border-violet-200' : 'bg-white border-slate-100 hover:bg-slate-50'
                    }`}
                    onClick={() => { setNarrative(h); }}
                    data-testid={`narrative-version-${h.narrative_version}`}
                  >
                    <Badge className="bg-slate-100 text-slate-600 text-[10px]">v{h.narrative_version}</Badge>
                    <span className="text-slate-600">{h.generated_by === 'ai' ? 'GPT-5.2' : 'Template'}</span>
                    <Badge className={`${confidenceColor(h.confidence || 0)} text-[10px] border`}>
                      {Math.round((h.confidence || 0) * 100)}%
                    </Badge>
                    <span className="ml-auto text-slate-400 text-[10px]">{new Date(h.created_at).toLocaleString()}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default IncidentNarrative;
