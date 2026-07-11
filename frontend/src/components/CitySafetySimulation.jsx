import React, { useState, useEffect, useCallback } from 'react';
import { Play, RotateCcw, Shield, Activity } from 'lucide-react';

/* ── Static simulation data (no WebSocket, no backend) ── */

const NODES = [
  { id: 0,  label: 'School',            x: 8,  y: 16 },
  { id: 1,  label: 'University',        x: 28, y: 10 },
  { id: 2,  label: 'Transit Hub',       x: 50, y: 20 },
  { id: 3,  label: 'Market District',   x: 72, y: 12 },
  { id: 4,  label: 'Academy',           x: 14, y: 46 },
  { id: 5,  label: 'Tech Park',         x: 38, y: 48 },
  { id: 6,  label: 'Western Corridor',  x: 60, y: 44 },
  { id: 7,  label: 'City Center',       x: 82, y: 48 },
  { id: 8,  label: 'High School',       x: 10, y: 76 },
  { id: 9,  label: 'Hospital Zone',     x: 32, y: 80 },
  { id: 10, label: 'Rail Station',      x: 54, y: 74 },
  { id: 11, label: 'Residential',       x: 76, y: 80 },
];

const EDGES = [
  [0,1],[1,2],[2,3],[0,4],[1,5],[2,6],[3,7],
  [4,5],[5,6],[6,7],[4,8],[5,9],[6,10],[7,11],
  [8,9],[9,10],[10,11],[1,4],[2,5],[5,10],[6,11],
];

const STEPS = [
  {
    phase: 'monitoring',
    title: 'City Monitoring Active',
    message: 'All 12 zones under continuous AI surveillance. Behavioral and environmental signals flowing at 450+ signals/sec.',
    duration: 3500,
    nodes: Object.fromEntries(NODES.map(n => [n.id, 'safe'])),
    edges: Object.fromEntries(EDGES.map((_, i) => [i, 'dim'])),
  },
  {
    phase: 'detection',
    title: 'Anomaly Detected — Western Corridor',
    message: 'Behavior anomaly flagged in Western Corridor. AI risk score surging from 0.2 to 0.78. Pattern deviation confirmed across 3 signals.',
    duration: 3500,
    nodes: { ...Object.fromEntries(NODES.map(n => [n.id, 'safe'])), 6: 'alert', 5: 'warning', 10: 'warning' },
    edges: { ...Object.fromEntries(EDGES.map((_, i) => [i, 'dim'])), 8: 'warning', 9: 'warning', 12: 'alert' },
  },
  {
    phase: 'propagation',
    title: 'Guardian Network Alerted',
    message: 'Command center activated. 4 guardians notified via push + SMS. Nearest patrol unit 2.3 km away — en route.',
    duration: 4000,
    nodes: { ...Object.fromEntries(NODES.map(n => [n.id, 'safe'])), 6: 'alert', 5: 'warning', 10: 'warning', 7: 'elevated', 2: 'elevated', 11: 'elevated' },
    edges: { ...Object.fromEntries(EDGES.map((_, i) => [i, 'dim'])), 8: 'alert', 9: 'alert', 12: 'alert', 5: 'warning', 13: 'warning', 15: 'warning', 19: 'warning' },
  },
  {
    phase: 'response',
    title: 'AI Response Deployed',
    message: 'Safe route recalculated. Risk containment active. Guardian confirmed visual contact. AI confidence: 94%.',
    duration: 4000,
    nodes: { ...Object.fromEntries(NODES.map(n => [n.id, 'safe'])), 6: 'responding', 5: 'system', 10: 'system' },
    edges: { ...Object.fromEntries(EDGES.map((_, i) => [i, 'dim'])), 8: 'system', 9: 'system', 12: 'system' },
  },
  {
    phase: 'resolved',
    title: 'Incident Resolved — All Clear',
    message: 'Incident contained in 2m 14s. All zones secure. Guardian network restored. AI model updated with new pattern data.',
    duration: 3500,
    nodes: Object.fromEntries(NODES.map(n => [n.id, 'resolved'])),
    edges: Object.fromEntries(EDGES.map((_, i) => [i, 'resolved'])),
  },
];

const STATE_STYLES = {
  safe:       { bg: '#10b981', shadow: '0 0 8px 2px rgba(16,185,129,0.4)',  ring: 'rgba(16,185,129,0.25)', pulse: false },
  elevated:   { bg: '#f59e0b', shadow: '0 0 12px 3px rgba(245,158,11,0.5)', ring: 'rgba(245,158,11,0.3)',  pulse: true },
  warning:    { bg: '#f97316', shadow: '0 0 14px 4px rgba(249,115,22,0.6)', ring: 'rgba(249,115,22,0.35)', pulse: true },
  alert:      { bg: '#ef4444', shadow: '0 0 18px 5px rgba(239,68,68,0.7)',  ring: 'rgba(239,68,68,0.4)',   pulse: true },
  responding: { bg: '#06b6d4', shadow: '0 0 16px 4px rgba(6,182,212,0.6)',  ring: 'rgba(6,182,212,0.35)',  pulse: true },
  system:     { bg: '#06b6d4', shadow: '0 0 10px 3px rgba(6,182,212,0.4)',  ring: 'rgba(6,182,212,0.25)',  pulse: false },
  resolved:   { bg: '#34d399', shadow: '0 0 12px 3px rgba(52,211,153,0.5)', ring: 'rgba(52,211,153,0.3)',  pulse: false },
};

const EDGE_STYLES = {
  dim:      { color: 'rgba(45,212,191,0.10)', width: 1 },
  warning:  { color: 'rgba(249,115,22,0.55)', width: 2 },
  alert:    { color: 'rgba(239,68,68,0.65)',   width: 2.5 },
  system:   { color: 'rgba(6,182,212,0.55)',   width: 2 },
  resolved: { color: 'rgba(52,211,153,0.20)',  width: 1.5 },
};

const PHASE_UI = {
  monitoring:  { label: 'MONITORING', cls: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20' },
  detection:   { label: 'ANOMALY',    cls: 'text-amber-400 bg-amber-500/10 border-amber-500/20' },
  propagation: { label: 'ALERT',      cls: 'text-red-400 bg-red-500/10 border-red-500/20' },
  response:    { label: 'RESPONDING', cls: 'text-cyan-400 bg-cyan-500/10 border-cyan-500/20' },
  resolved:    { label: 'RESOLVED',   cls: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20' },
};

/* ── Node component (HTML div, not SVG) ── */
function Node({ node, state }) {
  const s = STATE_STYLES[state] || STATE_STYLES.safe;
  return (
    <div
      className="absolute flex flex-col items-center"
      style={{
        left: `${node.x}%`,
        top: `${node.y}%`,
        transform: 'translate(-50%, -50%)',
        zIndex: 10,
      }}
      data-testid={`sim-node-${node.id}`}
    >
      {/* Pulse ring */}
      {s.pulse && (
        <div
          className="absolute rounded-full animate-ping"
          style={{
            width: 28,
            height: 28,
            backgroundColor: s.ring,
            animationDuration: '1.5s',
          }}
        />
      )}
      {/* Outer glow */}
      <div
        className="absolute rounded-full transition-all duration-500"
        style={{
          width: 22,
          height: 22,
          backgroundColor: s.ring,
        }}
      />
      {/* Core dot */}
      <div
        className="relative rounded-full transition-all duration-500"
        style={{
          width: 14,
          height: 14,
          backgroundColor: s.bg,
          boxShadow: s.shadow,
        }}
      >
        {/* Shine */}
        <div
          className="absolute rounded-full"
          style={{
            width: 5, height: 5,
            top: 2, left: 2,
            backgroundColor: 'rgba(255,255,255,0.35)',
          }}
        />
      </div>
      {/* Label */}
      <span
        className="mt-1 text-[9px] sm:text-[10px] font-medium whitespace-nowrap transition-colors duration-500"
        style={{ color: 'rgba(255,255,255,0.5)' }}
      >
        {node.label}
      </span>
    </div>
  );
}

/* ── Edge line (SVG overlay, percentage coords) ── */
function EdgeSVG({ edges, edgeStates }) {
  return (
    <svg className="absolute inset-0 w-full h-full" style={{ zIndex: 5 }} data-testid="sim-edges">
      {edges.map(([a, b], i) => {
        const na = NODES[a];
        const nb = NODES[b];
        const es = EDGE_STYLES[edgeStates[i]] || EDGE_STYLES.dim;
        const isActive = edgeStates[i] && edgeStates[i] !== 'dim';
        return (
          <line
            key={i}
            x1={`${na.x}%`} y1={`${na.y}%`}
            x2={`${nb.x}%`} y2={`${nb.y}%`}
            stroke={es.color}
            strokeWidth={es.width}
            strokeLinecap="round"
            style={{ transition: 'stroke 0.6s ease, stroke-width 0.6s ease' }}
          >
            {isActive && (
              <animate attributeName="stroke-opacity" values="0.5;1;0.5" dur="1.2s" repeatCount="indefinite" />
            )}
          </line>
        );
      })}
    </svg>
  );
}

/* ── Main Component ── */
export default function CitySafetySimulation() {
  const [running, setRunning] = useState(false);
  const [step, setStep] = useState(-1);
  const [done, setDone] = useState(false);

  const startSimulation = useCallback(() => {
    setDone(false);
    setStep(0);
    setRunning(true);
  }, []);

  // Auto-advance steps
  useEffect(() => {
    if (!running || step < 0 || step >= STEPS.length) return;
    const timer = setTimeout(() => {
      if (step < STEPS.length - 1) {
        setStep(s => s + 1);
      } else {
        setDone(true);
        setRunning(false);
      }
    }, STEPS[step].duration);
    return () => clearTimeout(timer);
  }, [running, step]);

  const cur = step >= 0 && step < STEPS.length ? STEPS[step] : null;
  const nodeStates = cur?.nodes || {};
  const edgeStates = cur?.edges || {};
  const phase = cur ? PHASE_UI[cur.phase] : null;

  return (
    <div data-testid="city-safety-simulation">
      {/* Header */}
      <div className="text-center mb-8">
        <p className="text-xs text-teal-400 font-bold uppercase tracking-widest mb-3">AI Safety Network Simulation</p>
        <h2 className="text-3xl sm:text-4xl font-bold text-white mb-4">City-Scale Safety Intelligence</h2>
        <p className="text-slate-400 max-w-xl mx-auto mb-6">Watch how Nischint detects, propagates, and resolves safety incidents across an entire city in real-time.</p>

        {!running && !done && (
          <button
            onClick={startSimulation}
            className="group inline-flex items-center gap-2 px-6 py-3 bg-gradient-to-r from-teal-500 to-emerald-500 text-white font-semibold rounded-xl hover:shadow-lg hover:shadow-teal-500/20 transition-all"
            data-testid="sim-start-btn"
          >
            <Play className="w-4 h-4" />
            Run City Safety Simulation
          </button>
        )}

        {done && (
          <button
            onClick={startSimulation}
            className="group inline-flex items-center gap-2 px-6 py-3 bg-white/5 border border-slate-700/60 text-slate-300 font-medium rounded-xl hover:bg-white/10 transition-colors"
            data-testid="sim-reset-btn"
          >
            <RotateCcw className="w-4 h-4" />
            Replay Simulation
          </button>
        )}
      </div>

      {/* Phase badge bar */}
      {cur && (
        <div className="flex items-center justify-between mb-4 px-2" data-testid="sim-status">
          <div className="flex items-center gap-3">
            <div className={`px-2.5 py-1 rounded-full border ${phase.cls}`}>
              <span className="text-[9px] font-bold uppercase tracking-widest">{phase.label}</span>
            </div>
            <span className="text-xs text-white font-semibold">{cur.title}</span>
          </div>
          <div className="flex items-center gap-2">
            {running && <Activity className="w-3 h-3 text-teal-400 animate-pulse" />}
            <span className="text-[10px] text-slate-500 font-mono">Step {step + 1}/{STEPS.length}</span>
          </div>
        </div>
      )}

      {/* ── CANVAS ── */}
      <div
        className="relative rounded-2xl border border-slate-800/40 overflow-hidden"
        style={{
          height: 420,
          background: 'linear-gradient(180deg, #060a14 0%, #0a1020 50%, #060a14 100%)',
        }}
        data-testid="sim-canvas"
      >
        {/* Grid background */}
        <div className="absolute inset-0 pointer-events-none" style={{
          backgroundImage: `
            linear-gradient(rgba(45,212,191,0.03) 1px, transparent 1px),
            linear-gradient(90deg, rgba(45,212,191,0.03) 1px, transparent 1px)
          `,
          backgroundSize: '50px 50px',
        }} />

        {/* Subtle radial highlights */}
        <div className="absolute inset-0 pointer-events-none" style={{
          background: `
            radial-gradient(ellipse at 20% 30%, rgba(16,185,129,0.04) 0%, transparent 40%),
            radial-gradient(ellipse at 75% 65%, rgba(6,182,212,0.04) 0%, transparent 40%)
          `,
        }} />

        {/* Edge lines (SVG with percentage coords) */}
        <EdgeSVG edges={EDGES} edgeStates={edgeStates} />

        {/* Nodes (HTML divs for reliable sizing) */}
        {NODES.map(node => (
          <Node key={node.id} node={node} state={nodeStates[node.id] || 'safe'} />
        ))}

        {/* Idle overlay */}
        {step < 0 && !done && (
          <div className="absolute inset-0 flex items-center justify-center bg-[#060a14]/80 backdrop-blur-sm" style={{ zIndex: 20 }}>
            <div className="text-center">
              <Shield className="w-12 h-12 text-slate-700 mx-auto mb-3" />
              <p className="text-sm text-slate-500">
                Click <span className="text-teal-400 font-medium">"Run City Safety Simulation"</span> to begin
              </p>
            </div>
          </div>
        )}
      </div>

      {/* Message panel */}
      {cur && (
        <div className="mt-4 px-4 py-3 rounded-xl bg-white/[0.02] border border-slate-800/40" data-testid="sim-message">
          <p className="text-xs text-slate-300 leading-relaxed">{cur.message}</p>
        </div>
      )}

      {/* Progress bar */}
      {(running || done) && (
        <div className="mt-3 flex gap-1.5" data-testid="sim-progress">
          {STEPS.map((_, i) => (
            <div
              key={i}
              className={`h-1 flex-1 rounded-full transition-all duration-500 ${
                i < step ? 'bg-emerald-500' :
                i === step ? (running ? 'bg-teal-400 animate-pulse' : 'bg-emerald-500') :
                'bg-slate-800'
              }`}
            />
          ))}
        </div>
      )}
    </div>
  );
}
