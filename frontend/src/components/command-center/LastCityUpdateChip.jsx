// Phase 8 + 9 — Last City Update Chip with click-to-expand flyout
//
// Persistent header chip showing fleet weather freshness + a click flyout
// listing the 9 cells sorted by impact (HIGH → MED → LOW). Reuses the
// already-fetched fleet weather payload — zero new API calls on click.

import React, { useEffect, useRef, useState, useCallback, useMemo } from 'react';
import { Clock, ArrowUp, ArrowDown } from 'lucide-react';
import { operatorApi } from '../../api';

const REFRESH_INTERVAL_MS = 60000;
const TIME_TICK_MS = 30000;
const IMPACT_RANK = { high: 0, medium: 1, low: 2 };

function relTime(iso) {
  if (!iso) return 'just now';
  const ms = Date.now() - new Date(iso).getTime();
  if (ms < 45000) return 'just now';
  const mins = Math.round(ms / 60000);
  if (mins < 60) return `${mins}m ago`;
  return `${Math.round(mins / 60)}h ago`;
}

function fullTimeFmt(iso) {
  if (!iso) return '—';
  try { return new Date(iso).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }); }
  catch (_) { return '—'; }
}

const IMPACT_PILL = {
  high:   'bg-rose-500/15 text-rose-200 border-rose-500/30',
  medium: 'bg-amber-500/15 text-amber-200 border-amber-500/30',
  low:    'bg-emerald-500/15 text-emerald-200 border-emerald-500/30',
};

/**
 * @param {boolean} wsConnected
 * @param {Object|null} fleetChange   — optional Phase 7 last-change snapshot
 *   used to mark recently-shifted cells with a tiny ↑/↓ arrow
 */
export const LastCityUpdateChip = ({ wsConnected = true, fleetChange = null }) => {
  const [grid, setGrid] = useState(null);
  const [, forceTick] = useState(0);
  const [open, setOpen] = useState(false);
  const wasConnectedRef = useRef(wsConnected);
  const inFlightRef = useRef(false);
  const wrapperRef = useRef(null);

  const fetchGrid = useCallback(async () => {
    if (inFlightRef.current) return;
    inFlightRef.current = true;
    try {
      const r = await operatorApi.getCommandCenterFleetWeather?.();
      if (r?.data) setGrid(r.data);
    } catch (_) { /* silent */ }
    finally { inFlightRef.current = false; }
  }, []);

  useEffect(() => {
    fetchGrid();
    const refreshIv = setInterval(fetchGrid, REFRESH_INTERVAL_MS);
    const tickIv = setInterval(() => forceTick(n => n + 1), TIME_TICK_MS);
    return () => { clearInterval(refreshIv); clearInterval(tickIv); };
  }, [fetchGrid]);

  useEffect(() => {
    if (wsConnected && !wasConnectedRef.current) fetchGrid();
    wasConnectedRef.current = wsConnected;
  }, [wsConnected, fetchGrid]);

  // Phase 9 — Outside-click + ESC to close flyout
  useEffect(() => {
    if (!open) return;
    const onDoc = (e) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target)) setOpen(false);
    };
    const onKey = (e) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', onDoc);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDoc);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  // Phase 9 — Sort cells by impact, then temp (high to low) for ties
  const sortedCells = useMemo(() => {
    if (!grid?.cells) return [];
    return [...grid.cells].sort((a, b) => {
      const r = (IMPACT_RANK[a.impact] ?? 3) - (IMPACT_RANK[b.impact] ?? 3);
      if (r !== 0) return r;
      const ta = typeof a.temp_c === 'number' ? a.temp_c : -999;
      const tb = typeof b.temp_c === 'number' ? b.temp_c : -999;
      if (tb !== ta) return tb - ta;
      return (a.cell_id || '').localeCompare(b.cell_id || '');
    });
  }, [grid]);

  // Phase 9 — Map cell_id → direction for arrow indicator
  const directionByCell = useMemo(() => {
    const m = {};
    if (Array.isArray(fleetChange?.breakdown)) {
      for (const b of fleetChange.breakdown) {
        if (b.cell_id) m[b.cell_id] = b.direction;
      }
    }
    return m;
  }, [fleetChange]);

  if (!grid || !Array.isArray(grid.cells) || grid.cells.length === 0) {
    return null;
  }

  const high = grid.cells.filter(c => c.impact === 'high').length;
  const med = grid.cells.filter(c => c.impact === 'medium').length;
  const total = grid.cells.length;

  return (
    <div ref={wrapperRef} className="relative inline-block">
      <button
        type="button"
        data-testid="last-city-update-chip"
        title={`Last full city scan at ${fullTimeFmt(grid.updated_at)} · ${total} zones evaluated`}
        onClick={() => setOpen(o => !o)}
        className="inline-flex items-center gap-2 px-2.5 py-1 rounded-md border border-slate-700 bg-slate-800/60 backdrop-blur hover:border-slate-500 transition-colors"
      >
        <Clock className="h-3 w-3 text-slate-400" />
        <span className="text-[10px] font-mono text-slate-300">
          Updated <span className="text-slate-100">{relTime(grid.updated_at)}</span>
        </span>
        <span className="text-slate-600">·</span>
        {high > 0 ? (
          <span className="text-[10px] font-bold tracking-wider px-1.5 py-0.5 rounded bg-rose-500/15 text-rose-200 border border-rose-500/30">{high} HIGH</span>
        ) : (
          <span className="text-[10px] font-mono text-slate-500">0 HIGH</span>
        )}
        {med > 0 ? (
          <span className="text-[10px] font-bold tracking-wider px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-200 border border-amber-500/30">{med} MED</span>
        ) : (
          <span className="text-[10px] font-mono text-slate-500">0 MED</span>
        )}
      </button>

      {open && (
        <div
          data-testid="last-city-update-flyout"
          className="absolute left-0 top-full mt-1.5 z-[1500] w-[320px] max-w-[calc(100vw-1.5rem)] max-h-[220px] overflow-y-auto rounded-md border border-slate-700 bg-slate-900/95 backdrop-blur shadow-xl"
          style={{ animation: 'cuFadeIn 0.15s ease-out' }}
        >
          {sortedCells.map((c) => {
            const dir = directionByCell[c.cell_id];
            const pill = IMPACT_PILL[c.impact] || IMPACT_PILL.low;
            return (
              <div
                key={c.cell_id}
                data-testid="last-city-update-flyout-row"
                className="flex items-center gap-2 px-3 py-1.5 text-[10px] font-mono border-b border-slate-800 last:border-0"
              >
                <span className="flex-1 text-slate-300 truncate">{c.cell_id}</span>
                {dir === 'up' && <ArrowUp className="h-2.5 w-2.5 text-rose-300" />}
                {dir === 'down' && <ArrowDown className="h-2.5 w-2.5 text-amber-200" />}
                <span className={`px-1.5 py-0.5 rounded border tracking-wider font-bold ${pill}`}>
                  {(c.impact || 'low').toUpperCase()}
                </span>
                <span className="text-slate-400 w-12 text-right">
                  {typeof c.temp_c === 'number' ? `${Math.round(c.temp_c)}°C` : '—'}
                </span>
                <span className="text-slate-500 w-20 truncate text-right capitalize">
                  {c.condition || '—'}
                </span>
              </div>
            );
          })}
          <style>{`
            @keyframes cuFadeIn { from { opacity: 0; transform: translateY(-4px) scale(0.98); } to { opacity: 1; transform: none; } }
          `}</style>
        </div>
      )}
    </div>
  );
};
