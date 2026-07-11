// REL-02 — pure helpers for LogTailCapsule.
// Kept in a separate module so unit tests can import without
// pulling React / axios into the Jest test runner.

export const LEVEL_TONE = {
  ERROR:    { bg: 'bg-red-900/30',    text: 'text-red-300',    badge: 'bg-red-500/80' },
  CRITICAL: { bg: 'bg-red-900/40',    text: 'text-red-200',    badge: 'bg-red-600' },
  WARNING:  { bg: 'bg-amber-900/25',  text: 'text-amber-200',  badge: 'bg-amber-500/80' },
  WARN:     { bg: 'bg-amber-900/25',  text: 'text-amber-200',  badge: 'bg-amber-500/80' },
  INFO:     { bg: 'bg-slate-800/30',  text: 'text-slate-300',  badge: 'bg-slate-600/80' },
  DEBUG:    { bg: 'bg-slate-800/20',  text: 'text-slate-400',  badge: 'bg-slate-700' },
  unknown:  { bg: 'bg-slate-800/30',  text: 'text-slate-300',  badge: 'bg-slate-700' },
};

// Parse one log line. Returns { level, ts, msg, raw }.
// Unparseable lines get level='unknown' but the raw is preserved
// for the copy / fallback render.
export const parseLine = (raw) => {
  if (!raw) return { level: 'unknown', ts: null, msg: '', raw };
  const trimmed = raw.trimStart();
  if (!trimmed.startsWith('{')) {
    return { level: 'unknown', ts: null, msg: raw, raw };
  }
  try {
    const obj = JSON.parse(trimmed);
    return {
      level: (obj.level || 'unknown').toString().toUpperCase(),
      ts:    obj.ts || null,
      msg:   obj.msg ?? obj.event ?? '',
      logger: obj.logger,
      raw,
    };
  } catch {
    return { level: 'unknown', ts: null, msg: raw, raw };
  }
};

// Compile a regex from user input. Invalid / empty → null
// (callers fall back to plain substring match).
export const safeRegex = (q) => {
  if (!q) return null;
  try { return new RegExp(q, 'i'); }
  catch { return null; }
};

// Filter parsed lines against a query string. Permissive on
// regex syntax errors — falls back to substring match.
export const filterLines = (lines, q) => {
  if (!q) return lines;
  const re = safeRegex(q);
  if (re) return lines.filter(l => re.test(l.raw));
  const ql = q.toLowerCase();
  return lines.filter(l => l.raw.toLowerCase().includes(ql));
};

// Format ISO `ts` as `HH:MM:SS.mmm` for compact log display.
export const fmtClock = (iso) => {
  if (!iso) return '';
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return '';
  const d = new Date(t);
  const hh = String(d.getHours()).padStart(2, '0');
  const mm = String(d.getMinutes()).padStart(2, '0');
  const ss = String(d.getSeconds()).padStart(2, '0');
  const ms = String(d.getMilliseconds()).padStart(3, '0');
  return `${hh}:${mm}:${ss}.${ms}`;
};
