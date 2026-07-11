// Smoke test for JourneyPolyline segmentation logic.
// Run: node /app/mobile/components/__smoke__/journey_polyline_smoke.js
const assert = require('assert');

// Inline copies of the two pure functions — keeps the test independent
// of the component's React/Maps imports which can't run under plain
// Node.
const GAP_DEGRADED_S = 15;
const GAP_OFFLINE_S  = 60;

function classifyEdge(prev, next) {
  const gap = next.gap_s ?? 0;
  if (gap >= GAP_OFFLINE_S) return 'offline';
  if (gap >= GAP_DEGRADED_S) return 'degraded';
  if (prev.quality === 'degraded' || next.quality === 'degraded') return 'degraded';
  return 'good';
}

function segmentize(points) {
  if (!points || points.length < 2) return [];
  const segs = [];
  let cur = {
    kind: classifyEdge(points[0], points[1]),
    coords: [
      { latitude: points[0].lat, longitude: points[0].lng },
      { latitude: points[1].lat, longitude: points[1].lng },
    ],
  };
  for (let i = 2; i < points.length; i++) {
    const kind = classifyEdge(points[i - 1], points[i]);
    const coord = { latitude: points[i].lat, longitude: points[i].lng };
    if (kind === cur.kind) {
      cur.coords.push(coord);
    } else {
      segs.push(cur);
      cur = {
        kind,
        coords: [
          { latitude: points[i - 1].lat, longitude: points[i - 1].lng },
          coord,
        ],
      };
    }
  }
  segs.push(cur);
  return segs;
}

function pt(seq, lat, lng, gap_s, quality = null) {
  return { seq, lat, lng, gap_s, quality, ts: null };
}

// ── Test 1: classifyEdge ────────────────────────────────────────────
console.log('T1: classifyEdge');
assert.strictEqual(classifyEdge(pt(1,0,0,null),  pt(2,0,0,5)),  'good');
assert.strictEqual(classifyEdge(pt(1,0,0,null),  pt(2,0,0,20)), 'degraded');
assert.strictEqual(classifyEdge(pt(1,0,0,null),  pt(2,0,0,120)),'offline');
assert.strictEqual(classifyEdge(pt(1,0,0,5,'degraded'), pt(2,0,0,5)), 'degraded');
assert.strictEqual(classifyEdge(pt(1,0,0,5), pt(2,0,0,5,'degraded')), 'degraded');
assert.strictEqual(classifyEdge(pt(1,0,0,5), pt(2,0,0,null)), 'good'); // gap null → 0
console.log('  ✓ all edge classifications correct');

// ── Test 2: segmentize handles empty / single point ─────────────────
console.log('T2: empty + single point');
assert.deepStrictEqual(segmentize([]), []);
assert.deepStrictEqual(segmentize([pt(1,0,0,null)]), []);
console.log('  ✓ empty & single-point → empty segments');

// ── Test 3: all good → one segment ──────────────────────────────────
console.log('T3: all good');
const goodPts = [pt(1,0,0,null), pt(2,0.001,0,5), pt(3,0.002,0,5), pt(4,0.003,0,5)];
const goodSegs = segmentize(goodPts);
assert.strictEqual(goodSegs.length, 1);
assert.strictEqual(goodSegs[0].kind, 'good');
assert.strictEqual(goodSegs[0].coords.length, 4);
console.log('  ✓ 4 good points → 1 segment of 4 coords');

// ── Test 4: good → degraded → good → offline sequence ───────────────
console.log('T4: good → degraded → offline bridging');
const mixPts = [
  pt(1, 0,     0, null),    // start
  pt(2, 0.001, 0, 5),       // good edge
  pt(3, 0.002, 0, 20),      // degraded edge (gap 20s)
  pt(4, 0.003, 0, 6),       // good edge again
  pt(5, 0.004, 0, 120),     // offline edge (gap 120s)
];
const mixSegs = segmentize(mixPts);
// Expected: good(1→2), degraded(2→3), good(3→4), offline(4→5)
assert.strictEqual(mixSegs.length, 4);
assert.deepStrictEqual(mixSegs.map(s => s.kind), ['good', 'degraded', 'good', 'offline']);
// Each segment should share the boundary vertex with neighbors → coords len = 2
mixSegs.forEach((s) => assert.strictEqual(s.coords.length, 2));
console.log('  ✓ mixed sequence → 4 segments [good,degraded,good,offline] with bridging');

// ── Test 5: consecutive same-kind edges group ───────────────────────
console.log('T5: consecutive same-kind grouping');
const groupPts = [
  pt(1, 0,     0, null),
  pt(2, 0.001, 0, 20),      // degraded
  pt(3, 0.002, 0, 25),      // degraded
  pt(4, 0.003, 0, 30),      // degraded
];
const groupSegs = segmentize(groupPts);
assert.strictEqual(groupSegs.length, 1);
assert.strictEqual(groupSegs[0].kind, 'degraded');
assert.strictEqual(groupSegs[0].coords.length, 4);
console.log('  ✓ 3 degraded edges → 1 segment of 4 coords');

console.log('\n✅ ALL 5 SEGMENTATION TESTS PASSED');
