"""
NISCHINT AI Brain — Decision Timeline (Explainability Layer)

Served by FastAPI at `/admin/ai-brain/timeline`. Not a dashboard — a live,
scrollable feed of brain decisions showing intelligence in action.

Each row renders:
    • Time · User type · Risk level · Action · Executed?
    • Triggers [voice, motion, ...] · Confidence
    • Cooldown applied?
    • Guardian selected (name + trust)
    • WHY THIS DECISION — human-readable reason (the killer feature)

Data source: GET /api/ai-brain/decisions?limit=50 — polled every 3s.
"""

AI_BRAIN_TIMELINE_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>NISCHINT · AI Brain · Decision Timeline</title>
<script src="https://cdn.tailwindcss.com"></script>
<style>
body{background:#0a0e17;color:#e6ebf5;font-family:ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto}
.card{background:#121826;border:1px solid #1f2937;border-radius:10px}
.row{background:#121826;border:1px solid #1f2937;border-radius:10px;transition:border-color .15s}
.row:hover{border-color:#334155}
.row.critical{border-left:3px solid #f43f5e}
.row.red{border-left:3px solid #fb923c}
.row.yellow{border-left:3px solid #eab308}
.row.green{border-left:3px solid #22c55e}
.chip{display:inline-flex;align-items:center;gap:4px;padding:2px 8px;border-radius:9999px;font-size:10px;font-weight:700;letter-spacing:.03em;text-transform:uppercase}
.chip-critical{background:#3f1d1d;color:#fca5a5;border:1px solid #dc2626}
.chip-red{background:#3b1e11;color:#fdba74;border:1px solid #ea580c}
.chip-yellow{background:#3b2f11;color:#fcd34d;border:1px solid #b45309}
.chip-green{background:#0f2c22;color:#6ee7b7;border:1px solid #059669}
.chip-neutral{background:#1e293b;color:#94a3b8;border:1px solid #334155}
.chip-exec{background:#0f2c22;color:#6ee7b7;border:1px solid #059669}
.chip-preview{background:#1e293b;color:#94a3b8;border:1px solid #334155}
.chip-cd{background:#2a1a3f;color:#c4b5fd;border:1px solid #6d28d9}
.trigger-pill{display:inline-block;font-size:10px;padding:1px 7px;border-radius:4px;background:#1e293b;color:#cbd5e1;border:1px solid #334155;margin-right:4px;margin-bottom:3px;font-variant-numeric:tabular-nums}
.reason{color:#e2e8f0;line-height:1.45;font-size:13.5px}
.reason::before{content:"▸ ";color:#818cf8;font-weight:700}
.conf-bar{height:4px;border-radius:9999px;background:#1f2937;overflow:hidden;width:60px}
.conf-fill{height:100%;background:linear-gradient(90deg,#f43f5e 0%,#eab308 40%,#22c55e 80%)}
.fb-btn{cursor:pointer;border:1px solid #334155;background:#1e293b;color:#cbd5e1;padding:3px 10px;border-radius:6px;font-size:11px;font-weight:600;transition:all .15s;display:inline-flex;align-items:center;gap:4px}
.fb-btn:hover:not(:disabled){filter:brightness(1.2);transform:translateY(-1px)}
.fb-btn:disabled{cursor:not-allowed;opacity:.55}
.fb-tp:hover:not(:disabled){border-color:#059669;color:#6ee7b7}
.fb-fa:hover:not(:disabled){border-color:#dc2626;color:#fca5a5}
.fb-miss:hover:not(:disabled){border-color:#b45309;color:#fcd34d}
.fb-recorded{font-size:11px;color:#6ee7b7;font-weight:600;display:inline-flex;align-items:center;gap:4px}
.fb-row{margin-top:8px;padding-top:8px;border-top:1px dashed #1f2937;display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.dot-live{display:inline-block;width:8px;height:8px;border-radius:9999px;background:#22c55e;box-shadow:0 0 10px #22c55e;animation:pulse 1.2s infinite;margin-right:7px}
.dot-stale{background:#64748b;box-shadow:none;animation:none}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}
@keyframes slideIn{from{opacity:0;transform:translateY(-6px)}to{opacity:1;transform:translateY(0)}}
.row-new{animation:slideIn .35s ease-out}
.mono{font-variant-numeric:tabular-nums;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.scroll::-webkit-scrollbar{width:6px}
.scroll::-webkit-scrollbar-thumb{background:#334155;border-radius:3px}
</style>
</head>
<body class="p-6">

<div class="max-w-5xl mx-auto">
  <header class="flex items-end justify-between mb-5">
    <div>
      <h1 class="text-xl font-bold text-white flex items-center">
        <span id="liveDot" class="dot-live"></span>
        AI Brain — Decision Timeline
      </h1>
      <p class="text-sm text-slate-400 mt-0.5">
        Every autonomous decision, explained. Updates every 3s.
      </p>
    </div>
    <div class="flex items-center gap-3 text-xs text-slate-400">
      <span>Showing <span id="countChip" class="text-white font-semibold">0</span> decisions</span>
      <span class="chip chip-neutral">Latest: <span id="latestTs" class="ml-1">—</span></span>
      <button id="pauseBtn" class="chip chip-neutral hover:brightness-125" style="cursor:pointer">⏸ Pause</button>
    </div>
  </header>

  <div class="card p-4 mb-4 text-xs text-slate-400">
    <span class="text-slate-300 font-semibold">Purpose:</span>
    This isn't analytics. It's the Explainability Layer — showing what your AI decided,
    what signals it saw, and <span class="text-white">why</span>. Each row is one autonomous decision.
  </div>

  <div id="timeline" class="space-y-2 scroll" style="max-height:calc(100vh - 220px);overflow-y:auto"></div>
  <p id="emptyMsg" class="text-center text-slate-500 text-sm py-10 hidden">
    No decisions yet. Trigger a signal via <code class="text-indigo-300">POST /api/ai-brain/decide</code> to see them appear here.
  </p>
</div>

<script>
const LEVEL_CLS = { CRITICAL:'critical', RED:'red', YELLOW:'yellow', GREEN:'green' };
const LEVEL_CHIP = { CRITICAL:'chip-critical', RED:'chip-red', YELLOW:'chip-yellow', GREEN:'chip-green' };
const seen = new Set();
let paused = false;

document.getElementById('pauseBtn').addEventListener('click', (e) => {
  paused = !paused;
  e.target.textContent = paused ? '▶ Resume' : '⏸ Pause';
  document.getElementById('liveDot').classList.toggle('dot-stale', paused);
});

function esc(s){return String(s==null?'':s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}

function fmtTime(iso) {
  try {
    const d = new Date(iso);
    const hh = String(d.getHours()).padStart(2,'0');
    const mm = String(d.getMinutes()).padStart(2,'0');
    const ss = String(d.getSeconds()).padStart(2,'0');
    return `${hh}:${mm}:${ss}`;
  } catch { return '—'; }
}

function renderRow(d) {
  const lvl = d.risk_level || 'GREEN';
  const lvlCls = LEVEL_CLS[lvl] || 'green';
  const lvlChip = LEVEL_CHIP[lvl] || 'chip-green';
  const confPct = Math.round((d.confidence || 0) * 100);
  const triggers = (d.triggers_fired || []).slice(0, 8);
  const g = d.guardian_selected;
  const execChip = d.executed
    ? `<span class="chip chip-exec" title="Brain acted autonomously">✓ Executed</span>`
    : `<span class="chip chip-preview">Preview</span>`;
  const cdChip = d.cooldown_applied
    ? `<span class="chip chip-cd" title="Original action was ${esc(d.original_action)}">Cooldown</span>`
    : '';
  const guardianStr = g
    ? `<span class="text-slate-400">Guardian:</span> <span class="text-white">${esc(g.name||g.id)}</span>
       <span class="text-indigo-300 mono">· Trust ${Number(g.effective_trust ?? g.trust_score ?? 0).toFixed(2)}</span>`
    : `<span class="text-slate-500">No guardian selected</span>`;
  const triggersHtml = triggers.length
    ? triggers.map(t => `<span class="trigger-pill">${esc(t)}</span>`).join('')
    : `<span class="text-slate-500 text-xs">no triggers fired</span>`;

  // Feedback row
  const fb = d.feedback;
  const eid = esc(d.event_id || '');
  let feedbackHtml;
  if (fb && fb.outcome) {
    const label = {
      true_positive: '👍 Correct',
      false_alarm:   '👎 False alarm',
      missed:        '⚠️ Missed severity',
      resolved:      '• Resolved',
    }[fb.outcome] || `• ${esc(fb.outcome)}`;
    const adj = fb.threshold_adjusted_to;
    const adjStr = (typeof adj === 'number' && adj !== 0)
      ? `<span class="text-indigo-300 mono ml-1">· threshold adj ${adj > 0 ? '+' : ''}${adj}</span>` : '';
    feedbackHtml = `<div class="fb-row"><span class="fb-recorded">✓ ${esc(label)}</span>${adjStr}</div>`;
  } else {
    feedbackHtml = `
      <div class="fb-row" data-eid="${eid}">
        <span class="text-xs text-slate-500">Was this right?</span>
        <button data-outcome="true_positive" class="fb-btn fb-tp" title="Reinforce — keep thresholds as-is">👍 Correct</button>
        <button data-outcome="false_alarm"   class="fb-btn fb-fa" title="Over-reacted — raise thresholds (confidence-weighted)">👎 False alarm</button>
        <button data-outcome="missed"        class="fb-btn fb-miss" title="Missed severity — lower thresholds (confidence-weighted)">⚠️ Missed severity</button>
      </div>`;
  }

  return `
    <div class="row ${lvlCls} row-new px-4 py-3" data-eid="${eid}">
      <div class="flex items-start justify-between gap-4">
        <div class="flex items-center gap-2 text-xs text-slate-400 min-w-[80px]">
          <span class="mono text-white">${fmtTime(d.decided_at)}</span>
        </div>
        <div class="flex-1 min-w-0">
          <div class="flex items-center gap-2 flex-wrap mb-1.5">
            <span class="chip ${lvlChip}">${esc(lvl)}</span>
            <span class="chip chip-neutral">${esc(d.user_type || 'adult')}</span>
            <span class="text-sm font-semibold text-white">${esc(d.recommended_action || '—')}</span>
            ${execChip} ${cdChip}
            <span class="text-xs text-slate-400 mono ml-1">user=${esc(d.user_id)}</span>
          </div>
          <div class="reason mb-2">${esc(d.reason || '—')}</div>
          <div class="mb-1.5">${triggersHtml}</div>
          <div class="flex items-center gap-4 text-xs flex-wrap">
            <span class="text-slate-400">Risk: <span class="text-white mono">${d.risk_score ?? '—'}</span></span>
            <span class="flex items-center gap-1.5">
              <span class="text-slate-400">Confidence</span>
              <span class="conf-bar"><span class="conf-fill" style="width:${confPct}%"></span></span>
              <span class="text-white mono">${confPct}%</span>
            </span>
            <span>${guardianStr}</span>
            ${d.latency_ms ? `<span class="text-slate-500 mono">· ${d.latency_ms}ms</span>` : ''}
          </div>
          ${feedbackHtml}
        </div>
      </div>
    </div>`;
}

async function tick() {
  if (paused) return;
  try {
    const r = await fetch('/api/ai-brain/decisions?limit=50', { cache: 'no-store' });
    if (!r.ok) return;
    const j = await r.json();
    const list = (j.decisions || []).slice().reverse(); // newest first
    const container = document.getElementById('timeline');
    const empty = document.getElementById('emptyMsg');

    if (!list.length) {
      container.innerHTML = '';
      empty.classList.remove('hidden');
      document.getElementById('countChip').textContent = '0';
      document.getElementById('latestTs').textContent = '—';
      return;
    }
    empty.classList.add('hidden');
    document.getElementById('countChip').textContent = list.length;
    document.getElementById('latestTs').textContent = fmtTime(list[0].decided_at);

    // Only re-render if set of event_ids changed (avoids flicker)
    const ids = list.map(d => d.event_id).join('|');
    if (ids === container.dataset.ids) return;
    container.dataset.ids = ids;

    const newIds = new Set(list.map(d => d.event_id));
    list.forEach(d => { if (!seen.has(d.event_id)) seen.add(d.event_id); });

    container.innerHTML = list.map(renderRow).join('');
  } catch (e) {
    console.warn('[AI_BRAIN_TIMELINE] fetch failed', e);
  }
}

tick();
setInterval(tick, 3000);

// ── Feedback delegation ──
// One-click POST to /api/ai-brain/feedback. Disables buttons, shows "✓ recorded".
// Also records the event_id locally so the row won't re-render the buttons on next poll.
const submittedIds = new Set();

document.addEventListener('click', async (ev) => {
  const btn = ev.target.closest('.fb-btn');
  if (!btn) return;
  const row = btn.closest('.fb-row');
  const eid = row?.getAttribute('data-eid');
  const outcome = btn.getAttribute('data-outcome');
  if (!eid || !outcome) return;

  // Optimistic disable
  row.querySelectorAll('.fb-btn').forEach(b => b.disabled = true);
  btn.textContent = '⏳ submitting…';

  try {
    const r = await fetch('/api/ai-brain/feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ event_id: eid, outcome }),
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) {
      throw new Error(j.detail || ('HTTP ' + r.status));
    }
    const adj = j?.feedback?.threshold_adjusted_to;
    const adjStr = (typeof adj === 'number' && adj !== 0)
      ? ` · threshold adj ${adj > 0 ? '+' : ''}${adj}` : '';
    const labelMap = {
      true_positive: '👍 Correct',
      false_alarm:   '👎 False alarm',
      missed:        '⚠️ Missed severity',
    };
    row.innerHTML = `<span class="fb-recorded">✓ ${labelMap[outcome] || outcome} recorded${adjStr}</span>`;
    submittedIds.add(eid);
    // Force re-render next tick so the row is marked as already-fed-back
    const container = document.getElementById('timeline');
    if (container) container.dataset.ids = '';
  } catch (e) {
    btn.textContent = '⚠️ retry';
    row.querySelectorAll('.fb-btn').forEach(b => b.disabled = false);
    console.warn('[AI_BRAIN_FEEDBACK] submit failed', e);
  }
});
</script>
</body>
</html>
"""
