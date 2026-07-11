"""
NISCHINT Journey Engine — Rollout Control Dashboard (HTML)

Static page served by FastAPI at /admin/journey/rollout.
Renders real-time rollout state, emergency kill switch, allowlist table,
stage control, and delivery confidence metrics.
"""

ROLLOUT_DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>NISCHINT · Journey Rollout Control</title>
<script src="https://cdn.tailwindcss.com"></script>
<style>
body{background:#0a0e17;color:#e6ebf5;font-family:ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto}
.card{background:#121826;border:1px solid #1f2937;border-radius:10px}
.kill-btn{background:linear-gradient(180deg,#f43f5e 0%,#881337 100%);box-shadow:0 0 18px rgba(244,63,94,.45)}
.kill-btn:hover{filter:brightness(1.1)}
.green-btn{background:linear-gradient(180deg,#22c55e 0%,#065f46 100%);box-shadow:0 0 18px rgba(34,197,94,.3)}
.chip{display:inline-flex;align-items:center;gap:6px;padding:2px 9px;border-radius:9999px;font-size:11px;font-weight:600}
.chip-on{background:#064e3b;color:#6ee7b7;border:1px solid #059669}
.chip-off{background:#3f1d1d;color:#fca5a5;border:1px solid #dc2626}
.chip-warn{background:#3b2f11;color:#fcd34d;border:1px solid #b45309}
.chip-neutral{background:#1e293b;color:#94a3b8;border:1px solid #334155}
.metric-val{font-variant-numeric:tabular-nums;font-weight:700}
table th{text-align:left;font-size:11px;color:#94a3b8;text-transform:uppercase;letter-spacing:.04em}
table td{font-size:13px}
input,textarea,select{background:#0b1120;border:1px solid #1f2937;color:#e6ebf5;border-radius:6px;padding:7px 10px;width:100%}
input:focus,textarea:focus,select:focus{outline:none;border-color:#6366f1}
.btn{padding:7px 14px;border-radius:6px;font-weight:600;font-size:13px;cursor:pointer;transition:filter .15s}
.btn:hover{filter:brightness(1.1)}
.btn-primary{background:#4f46e5;color:#fff}
.btn-ghost{background:#1f2937;color:#e6ebf5}
.btn-danger{background:#dc2626;color:#fff}
.dot{display:inline-block;width:8px;height:8px;border-radius:9999px;margin-right:6px}
.dot-on{background:#22c55e;box-shadow:0 0 8px #22c55e}
.dot-off{background:#64748b}
.dot-emergency{background:#f43f5e;box-shadow:0 0 10px #f43f5e;animation:pulse 1.2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
.pill{font-size:10px;padding:1px 6px;border-radius:4px;background:#1e293b;color:#94a3b8}
.confidence-bar{height:6px;border-radius:9999px;background:#1f2937;overflow:hidden}
.confidence-fill{height:100%;background:linear-gradient(90deg,#f43f5e 0%,#eab308 40%,#22c55e 80%)}
</style>
</head>
<body class="p-6">

<div class="max-w-7xl mx-auto">

  <!-- Header -->
  <div class="flex items-center justify-between mb-6">
    <div>
      <h1 class="text-2xl font-bold tracking-tight">NISCHINT <span class="text-indigo-400">Rollout Control</span></h1>
      <p class="text-xs text-slate-400 mt-1">Staged rollout · dual-control gate · delivery confidence metrics</p>
    </div>
    <div class="flex items-center gap-2">
      <span class="chip chip-neutral" id="refreshChip">auto-refresh 5s</span>
      <button onclick="load()" class="btn btn-ghost">Refresh</button>
    </div>
  </div>

  <!-- Global Status Row -->
  <div class="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">

    <!-- Kill Switch Card -->
    <div class="card p-5 col-span-1 md:col-span-2">
      <div class="flex items-center justify-between mb-3">
        <div>
          <div class="text-[11px] uppercase tracking-wider text-slate-400">Global Kill Switch</div>
          <div class="text-lg font-bold mt-1" id="killStatus">—</div>
        </div>
        <div id="killIndicator"></div>
      </div>
      <div class="flex gap-2">
        <button id="killBtn" onclick="engageKill()" class="btn kill-btn text-white">Engage Emergency Stop</button>
        <button id="releaseBtn" onclick="releaseKill()" class="btn green-btn text-white hidden">Release Emergency Stop</button>
      </div>
      <p class="text-[11px] text-slate-500 mt-3">When engaged, ALL real delivery is blocked regardless of env flag or allowlist. Fail-safe override.</p>
    </div>

    <!-- Live Flag -->
    <div class="card p-5">
      <div class="text-[11px] uppercase tracking-wider text-slate-400">Live Delivery Flag</div>
      <div class="text-lg font-bold mt-1"><span id="liveFlagDot" class="dot dot-off"></span><span id="liveFlag">—</span></div>
      <p class="text-[11px] text-slate-500 mt-3">Set via <code class="pill">JOURNEY_LIVE_DELIVERY</code> in backend/.env. Read-only here.</p>
    </div>

    <!-- Current Stage -->
    <div class="card p-5">
      <div class="text-[11px] uppercase tracking-wider text-slate-400">Current Rollout Stage</div>
      <div class="text-lg font-bold mt-1" id="currentStage">—</div>
      <select id="stageSelect" onchange="setStage()" class="mt-3 text-xs"></select>
    </div>

  </div>

  <!-- Stage Progress -->
  <div class="card p-5 mb-6">
    <div class="text-[11px] uppercase tracking-wider text-slate-400 mb-3">Stage Progress</div>
    <div id="stageRows" class="space-y-3"></div>
  </div>

  <!-- Metrics Row -->
  <div class="grid grid-cols-2 md:grid-cols-6 gap-3 mb-6">
    <div class="card p-4"><div class="text-[10px] uppercase text-slate-400">Total SOS</div><div class="metric-val text-xl mt-1" id="mSos">0</div></div>
    <div class="card p-4"><div class="text-[10px] uppercase text-slate-400">SMS Real</div><div class="metric-val text-xl mt-1 text-emerald-400" id="mSmsReal">0</div></div>
    <div class="card p-4"><div class="text-[10px] uppercase text-slate-400">SMS Sim</div><div class="metric-val text-xl mt-1 text-slate-400" id="mSmsSim">0</div></div>
    <div class="card p-4"><div class="text-[10px] uppercase text-slate-400">Push Real</div><div class="metric-val text-xl mt-1 text-emerald-400" id="mPushReal">0</div></div>
    <div class="card p-4"><div class="text-[10px] uppercase text-slate-400">Avg ACK</div><div class="metric-val text-xl mt-1" id="mAck">—</div></div>
    <div class="card p-4"><div class="text-[10px] uppercase text-slate-400">Avg Confidence</div><div class="metric-val text-xl mt-1" id="mConf">—</div></div>
  </div>

  <!-- Allowlist + Add Form -->
  <div class="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-6">

    <!-- Allowlist Table -->
    <div class="card p-5 lg:col-span-2">
      <div class="flex items-center justify-between mb-4">
        <div class="text-sm font-semibold">Session Allowlist</div>
        <div class="flex gap-2">
          <select id="filterStage" onchange="load()" class="text-xs w-auto"><option value="">All stages</option></select>
          <label class="text-xs flex items-center gap-2"><input type="checkbox" id="filterEnabled" onchange="load()" class="w-auto"> Enabled only</label>
        </div>
      </div>
      <div class="overflow-x-auto">
        <table class="w-full">
          <thead><tr class="border-b border-slate-800">
            <th class="py-2 pr-3">Session ID</th>
            <th class="py-2 pr-3">Stage</th>
            <th class="py-2 pr-3">Status</th>
            <th class="py-2 pr-3">Added</th>
            <th class="py-2 pr-3">Notes</th>
            <th class="py-2 pr-3"></th>
          </tr></thead>
          <tbody id="allowlistBody"></tbody>
        </table>
        <div id="allowlistEmpty" class="text-center text-slate-500 text-sm py-8 hidden">No sessions in allowlist — add one to start the rollout.</div>
      </div>
    </div>

    <!-- Add / Bulk Form -->
    <div class="card p-5">
      <div class="text-sm font-semibold mb-3">Add to Allowlist</div>
      <div class="space-y-3 text-xs">
        <div>
          <label class="text-slate-400">Session ID (or multiple, one per line)</label>
          <textarea id="sidInput" rows="3" placeholder="user_123&#10;user_456"></textarea>
        </div>
        <div>
          <label class="text-slate-400">Stage</label>
          <select id="addStage"></select>
        </div>
        <div>
          <label class="text-slate-400">Notes</label>
          <input id="notesInput" placeholder="pilot batch 1, internal testing..." />
        </div>
        <div class="flex items-center gap-2">
          <label class="text-slate-400 flex items-center gap-2"><input type="checkbox" id="addEnabled" checked class="w-auto"> Enabled</label>
        </div>
        <button onclick="bulkAdd()" class="btn btn-primary w-full">Add Session(s)</button>
        <p class="text-[10px] text-slate-500">Enabled sessions receive real SMS/Push when the live flag is on and emergency stop is released.</p>
      </div>
    </div>
  </div>

  <!-- Top Sessions -->
  <div class="card p-5">
    <div class="text-sm font-semibold mb-3">Top Sessions by SOS Count <span class="text-[11px] text-slate-500 font-normal">· Delivery Confidence Leaderboard</span></div>
    <div class="overflow-x-auto">
      <table class="w-full">
        <thead><tr class="border-b border-slate-800">
          <th class="py-2 pr-3">Session</th>
          <th class="py-2 pr-3">SOS</th>
          <th class="py-2 pr-3">SMS R / Sim</th>
          <th class="py-2 pr-3">Push R / Sim</th>
          <th class="py-2 pr-3">ACKs</th>
          <th class="py-2 pr-3">Confidence</th>
        </tr></thead>
        <tbody id="topBody"></tbody>
      </table>
      <div id="topEmpty" class="text-center text-slate-500 text-sm py-6 hidden">No telemetry yet — trigger some SOS events.</div>
    </div>
  </div>

  <div class="text-center text-slate-600 text-[10px] mt-6">NISCHINT Rollout Control v1 · Mongo-backed · Fail-safe engaged</div>
</div>

<script>
const API = window.location.origin + '/api/journey/rollout';
let currentConfig = {};

async function j(u,o){ const r = await fetch(u,o); return r.json(); }

function renderStages(stages){
  const sel = document.getElementById('stageSelect');
  const filt = document.getElementById('filterStage');
  const add = document.getElementById('addStage');
  sel.innerHTML = ''; add.innerHTML = '';
  filt.querySelectorAll('option:not(:first-child)').forEach(o=>o.remove());
  Object.entries(stages).forEach(([k,v])=>{
    const label = `${k.replace('stage','Stage ').replace('_',' ')} · target ${v.target}`;
    sel.insertAdjacentHTML('beforeend', `<option value="${k}">${label}</option>`);
    add.insertAdjacentHTML('beforeend', `<option value="${k}">${label}</option>`);
    filt.insertAdjacentHTML('beforeend', `<option value="${k}">${label}</option>`);
  });
}

async function load(){
  try {
    const cfg = await j(API + '/config');
    currentConfig = cfg;
    renderStages(cfg.stages);

    // Kill switch
    const killed = cfg.config.emergency_stop;
    document.getElementById('killStatus').innerHTML = killed
      ? '<span class="text-rose-400">ENGAGED — all real delivery blocked</span>'
      : '<span class="text-emerald-400">Released — normal operation</span>';
    document.getElementById('killIndicator').innerHTML = killed
      ? '<span class="dot dot-emergency"></span>'
      : '<span class="dot dot-on"></span>';
    document.getElementById('killBtn').classList.toggle('hidden', killed);
    document.getElementById('releaseBtn').classList.toggle('hidden', !killed);

    // Live flag
    const live = cfg.env.live_delivery_flag;
    document.getElementById('liveFlag').textContent = live ? 'ON (LIVE)' : 'OFF (simulator)';
    document.getElementById('liveFlagDot').className = 'dot ' + (live ? 'dot-on' : 'dot-off');

    // Stage
    document.getElementById('currentStage').textContent = (cfg.stages[cfg.config.current_stage]?.purpose || cfg.config.current_stage);
    document.getElementById('stageSelect').value = cfg.config.current_stage;

    // Stage rows
    const rows = Object.entries(cfg.stages).map(([k,v])=>{
      const count = cfg.allowlist_counts.by_stage[k] || 0;
      const pct = Math.min(100, Math.round(count/v.target*100));
      const active = k === cfg.config.current_stage;
      return `<div class="flex items-center gap-3 ${active?'':'opacity-60'}">
        <div class="w-44 shrink-0 text-xs">
          <div class="font-semibold">${k.replace('stage','Stage ').replace('_',' ')}</div>
          <div class="text-slate-500 text-[10px]">${v.purpose}</div>
        </div>
        <div class="flex-1"><div class="confidence-bar"><div class="confidence-fill" style="width:${pct}%"></div></div></div>
        <div class="text-xs tabular-nums w-20 text-right">${count} / ${v.target}</div>
      </div>`;
    }).join('');
    document.getElementById('stageRows').innerHTML = rows;

    // Allowlist
    const stage = document.getElementById('filterStage').value;
    const enabledOnly = document.getElementById('filterEnabled').checked;
    const ql = new URLSearchParams();
    if (stage) ql.set('stage', stage);
    if (enabledOnly) ql.set('enabled_only', 'true');
    const al = await j(API + '/allowlist?' + ql.toString());
    const tbody = document.getElementById('allowlistBody');
    if (al.count === 0) { tbody.innerHTML=''; document.getElementById('allowlistEmpty').classList.remove('hidden'); }
    else {
      document.getElementById('allowlistEmpty').classList.add('hidden');
      tbody.innerHTML = al.allowlist.map(r => `<tr class="border-b border-slate-800/60">
        <td class="py-2 pr-3 font-mono text-xs">${esc(r.session_id)}</td>
        <td class="py-2 pr-3"><span class="pill">${r.stage}</span></td>
        <td class="py-2 pr-3"><span class="chip ${r.enabled?'chip-on':'chip-off'}">${r.enabled?'enabled':'disabled'}</span></td>
        <td class="py-2 pr-3 text-slate-400 text-xs">${r.added_at ? new Date(r.added_at).toLocaleString() : '—'}</td>
        <td class="py-2 pr-3 text-slate-400 text-xs">${esc(r.notes||'')}</td>
        <td class="py-2 pr-3 text-right">
          <button onclick="toggle('${esc(r.session_id)}', ${!r.enabled}, '${r.stage}')" class="btn btn-ghost text-xs">${r.enabled?'Disable':'Enable'}</button>
          <button onclick="del('${esc(r.session_id)}')" class="btn btn-danger text-xs">Remove</button>
        </td>
      </tr>`).join('');
    }

    // Metrics
    const m = await j(API + '/metrics');
    document.getElementById('mSos').textContent = m.totals.sos;
    document.getElementById('mSmsReal').textContent = m.totals.sms_real;
    document.getElementById('mSmsSim').textContent = m.totals.sms_sim;
    document.getElementById('mPushReal').textContent = m.totals.push_real;
    document.getElementById('mAck').textContent = m.totals.avg_ack_seconds != null ? m.totals.avg_ack_seconds + 's' : '—';
    document.getElementById('mConf').textContent = m.totals.avg_delivery_confidence != null ? m.totals.avg_delivery_confidence : '—';

    // Top sessions
    const topB = document.getElementById('topBody');
    if (!m.top_sessions.length) { topB.innerHTML=''; document.getElementById('topEmpty').classList.remove('hidden'); }
    else {
      document.getElementById('topEmpty').classList.add('hidden');
      topB.innerHTML = m.top_sessions.map(s => {
        const avgConf = s.confidence_count ? Math.round(s.confidence_sum/s.confidence_count) : 0;
        return `<tr class="border-b border-slate-800/60">
          <td class="py-2 pr-3 font-mono text-xs">${esc(s.session_id)}</td>
          <td class="py-2 pr-3 tabular-nums">${s.sos_count}</td>
          <td class="py-2 pr-3 tabular-nums"><span class="text-emerald-400">${s.sms_real}</span> / <span class="text-slate-500">${s.sms_sim}</span></td>
          <td class="py-2 pr-3 tabular-nums"><span class="text-emerald-400">${s.push_real}</span> / <span class="text-slate-500">${s.push_sim}</span></td>
          <td class="py-2 pr-3 tabular-nums">${s.ack_count}</td>
          <td class="py-2 pr-3">
            <div class="flex items-center gap-2">
              <div class="confidence-bar flex-1 w-20"><div class="confidence-fill" style="width:${avgConf}%"></div></div>
              <span class="tabular-nums text-xs w-8">${avgConf}</span>
            </div>
          </td>
        </tr>`;
      }).join('');
    }
  } catch(e) {
    console.error(e);
  }
}

function esc(s){ return String(s||'').replace(/[<>"'&]/g, c => ({'<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;','&':'&amp;'})[c]); }

async function engageKill(){
  if (!confirm('ENGAGE EMERGENCY STOP?\n\nThis will block ALL real SMS/Push delivery immediately.')) return;
  await j(API + '/emergency-stop?actor=dashboard', {method:'POST'});
  load();
}
async function releaseKill(){
  if (!confirm('RELEASE emergency stop?\n\nReal delivery will resume for allowlisted sessions.')) return;
  await j(API + '/emergency-release?actor=dashboard', {method:'POST'});
  load();
}
async function setStage(){
  const v = document.getElementById('stageSelect').value;
  await j(API + '/config', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({current_stage: v, actor:'dashboard'})});
  load();
}
async function bulkAdd(){
  const raw = document.getElementById('sidInput').value;
  const ids = raw.split(/\n|,/).map(s=>s.trim()).filter(Boolean);
  if (!ids.length) { alert('Enter at least one session ID'); return; }
  const stage = document.getElementById('addStage').value;
  const notes = document.getElementById('notesInput').value;
  const enabled = document.getElementById('addEnabled').checked;
  await j(API + '/allowlist/bulk', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({session_ids: ids, enabled, stage, notes, added_by: 'dashboard'})});
  document.getElementById('sidInput').value = '';
  document.getElementById('notesInput').value = '';
  load();
}
async function toggle(sid, enable, stage){
  await j(API + '/allowlist', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({session_id: sid, enabled: enable, stage, added_by:'dashboard'})});
  load();
}
async function del(sid){
  if (!confirm('Remove '+sid+' from allowlist?')) return;
  await fetch(API + '/allowlist/' + encodeURIComponent(sid), {method:'DELETE'});
  load();
}

load();
setInterval(load, 5000);
</script>
</body>
</html>
"""
