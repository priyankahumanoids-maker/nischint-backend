// REL-02 — LogTailCapsule pure-helper tests.
//
// We test the parse / filter / regex helpers (no React mount needed).
// The component itself is covered indirectly by the production build.

import { parseLine, filterLines, safeRegex, fmtClock } from '../components/command-center/logTailHelpers';

describe('parseLine', () => {
  test('parses well-formed JSON log line', () => {
    const raw = '{"ts":"2026-05-29T10:00:00Z","level":"info","msg":"hello","logger":"x"}';
    const out = parseLine(raw);
    expect(out.level).toBe('INFO');
    expect(out.msg).toBe('hello');
    expect(out.ts).toBe('2026-05-29T10:00:00Z');
    expect(out.raw).toBe(raw);
  });

  test('non-JSON line keeps level=unknown and msg=raw', () => {
    const raw = 'Traceback (most recent call last):';
    const out = parseLine(raw);
    expect(out.level).toBe('unknown');
    expect(out.msg).toBe(raw);
  });

  test('malformed JSON falls back gracefully', () => {
    const out = parseLine('{"ts": INVALID JSON');
    expect(out.level).toBe('unknown');
    expect(out.raw).toBe('{"ts": INVALID JSON');
  });

  test('uppercases ERROR/WARNING for the colour key', () => {
    expect(parseLine('{"level":"error","msg":"x"}').level).toBe('ERROR');
    expect(parseLine('{"level":"warning","msg":"x"}').level).toBe('WARNING');
  });

  test('empty input returns unknown', () => {
    const out = parseLine('');
    expect(out.level).toBe('unknown');
  });

  test('missing level field gets unknown', () => {
    expect(parseLine('{"ts":"2026-05-29T10:00:00Z","msg":"x"}').level).toBe('UNKNOWN');
  });

  test('falls back to event field when msg absent', () => {
    expect(parseLine('{"level":"info","event":"hello"}').msg).toBe('hello');
  });
});

describe('safeRegex', () => {
  test('valid regex compiles', () => {
    expect(safeRegex('error|warn')).toBeInstanceOf(RegExp);
  });

  test('empty input returns null', () => {
    expect(safeRegex('')).toBeNull();
    expect(safeRegex(null)).toBeNull();
  });

  test('invalid regex returns null (caller falls back to substring)', () => {
    expect(safeRegex('[invalid')).toBeNull();
  });

  test('case-insensitive by default', () => {
    const re = safeRegex('Error');
    expect(re.test('an error occurred')).toBe(true);
  });
});

describe('filterLines', () => {
  const lines = [
    parseLine('{"level":"info","msg":"hello world"}'),
    parseLine('{"level":"error","msg":"db connection failed"}'),
    parseLine('Plain text traceback'),
  ];

  test('empty query returns everything', () => {
    expect(filterLines(lines, '')).toHaveLength(3);
  });

  test('substring match (no regex)', () => {
    const out = filterLines(lines, 'hello');
    expect(out).toHaveLength(1);
    expect(out[0].msg).toContain('hello');
  });

  test('regex match', () => {
    const out = filterLines(lines, 'db|trace');
    expect(out).toHaveLength(2);
  });

  test('invalid regex falls back to substring — never throws', () => {
    // `[invalid` is malformed; safeRegex returns null;
    // filterLines must fall back to substring match.
    const out = filterLines(lines, '[invalid');
    expect(out).toHaveLength(0);
    // Must not have thrown.
  });

  test('case-insensitive substring fallback', () => {
    const out = filterLines(lines, 'TRACEBACK');
    expect(out).toHaveLength(1);
  });
});

describe('fmtClock', () => {
  test('ISO timestamp renders HH:MM:SS.mmm', () => {
    const s = fmtClock('2026-05-29T14:25:36.789Z');
    expect(s).toMatch(/^\d{2}:\d{2}:\d{2}\.\d{3}$/);
  });

  test('null/empty returns empty string', () => {
    expect(fmtClock(null)).toBe('');
    expect(fmtClock('')).toBe('');
  });

  test('malformed input returns empty string', () => {
    expect(fmtClock('not-a-date')).toBe('');
  });
});
