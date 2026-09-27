// Sentinel runs ARIA on the server (sentinel_engine.py). This test runs the
// ORIGINAL ARIA code from protrader_mobile.html and the Python port on the
// same candles and fails on any disagreement, so the two cannot drift.
//
//   node --test tests/*.test.cjs
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {execFileSync} = require('node:child_process');

const root = path.join(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'protrader_mobile.html'), 'utf8');
const cut = (a, b) => {
  const i = html.indexOf(a), j = html.indexOf(b, i);
  assert.ok(i >= 0 && j > i, `markers not found: ${a} … ${b}`);
  const seg = html.slice(i, j), open = seg.lastIndexOf('/*');
  // Drop a comment banner the end marker sits inside.
  return open >= 0 && seg.indexOf('*/', open) < 0 ? seg.slice(0, open) : seg;
};
const source = [
  cut('function calcEMA(', 'CHART — TradingView'),
  cut('const ARIA_LAWS', 'function renderARIA'),
  cut('const PATTERNS = [', 'function runPatternScanner'),
].join('\n');

// Deterministic random walk with regime changes, gaps and flat bars.
function makeCandles(seed, n, start, vol) {
  let s = seed >>> 0;
  const rnd = () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296);
  const out = []; let px = start, drift = 0;
  for (let i = 0; i < n; i++) {
    if (i % 40 === 0) drift = (rnd() - 0.5) * vol * 0.6;
    const o = px, c = Math.max(1e-6, o + drift + (rnd() - 0.5) * vol * 2);
    const flat = rnd() < 0.02;
    const h = flat ? o : Math.max(o, c) + rnd() * vol;
    const l = flat ? o : Math.min(o, c) - rnd() * vol;
    out.push({time: 1780000000 + i * 900, open: +o.toFixed(5), high: +h.toFixed(5),
              low: +l.toFixed(5), close: +(flat ? o : c).toFixed(5)});
    px = c;
  }
  return out;
}

function runJS(cdles, sym, hour, newsWeek) {
  class FixedDate extends Date { getUTCHours() { return hour; } }
  const S = {candles: cdles, sym, tf: '15m', dp: 5, balance: 10000, riskPct: 1, newsWeek, activePatterns: []};
  const ctx = vm.createContext({S, Date: FixedDate, Math, Number, JSON});
  vm.runInContext(source, ctx);
  return vm.runInContext(`(() => {
    const cdles = S.candles, closes = cdles.map(x => x.close), n = closes.length;
    const ema20v = calcEMA(closes, 20), ema50v = calcEMA(closes, 50), ema200v = calcEMA(closes, 200);
    const rsiV = calcRSI(closes), atrV = calcATR(cdles, 14), macdV = calcMACD(closes), stochV = calcStoch(cdles);
    const mcc = ariaMCC(cdles, closes, ema20v, ema50v, atrV);
    const wyck = ariaWyckoff(cdles, closes, ema20v, ema50v);
    const dir = (closes[n-1] > ema20v[n-1] && ema20v[n-1] > ema50v[n-1]) ? 'buy' : 'sell';
    const pat = getPatternAlignment(dir);
    const g = ariaGates(cdles, closes, ema20v, ema50v, ema200v, rsiV, macdV, stochV, atrV, pat);
    const v = ariaVerdict(g.score, mcc, S.sym, g.dir);
    const e = ariaEntry(cdles, closes, atrV, g.dir, mcc);
    return {dir: g.dir, score: g.score, gates: g.gates.map(x => !!x.pass), mcc: mcc.code,
            wyckoff: wyck.phase, pattern: pat, verdict: v.v, sl: e.slLevel, tp2: e.tp2};
  })()`, ctx);
}

const cases = [];
for (let k = 0; k < 60; k++) {
  const vol = [0.4, 3, 0.0008, 25][k % 4], start = [100, 1000, 1.1, 20000][k % 4];
  const all = makeCandles(1000 + k, 260 + (k * 7) % 80, start, vol);
  // Several cut points per series: different last bars, different patterns.
  for (const back of [0, 3, 11, 29]) {
    const c = all.slice(0, all.length - back);
    cases.push({c, sym: k % 5 === 0 ? 'frxNAS100' : 'frxXAUUSD', hour: [1, 3, 9, 14, 21][k % 5], news: k % 2 === 0});
  }
}

test('Python ARIA port matches the terminal ARIA engine', () => {
  const py = JSON.parse(execFileSync('python3', ['-c', `
import json, sys
sys.path.insert(0, ${JSON.stringify(root)})
from sentinel_engine import evaluate
cases = json.load(sys.stdin)
out = []
for k in cases:
    r = evaluate(k["c"], k["sym"], k["hour"], k["news"])
    out.append({kk: r[kk] for kk in ("dir","score","gates","mcc","wyckoff","pattern","verdict","sl","tp2")})
print(json.dumps(out))
`], {input: JSON.stringify(cases), maxBuffer: 64 << 20}).toString());

  let verdicts = {};
  cases.forEach((k, i) => {
    const js = JSON.parse(JSON.stringify(runJS(k.c, k.sym, k.hour, k.news))), p = py[i];
    verdicts[js.verdict] = (verdicts[js.verdict] || 0) + 1;
    for (const f of ['dir', 'score', 'mcc', 'wyckoff', 'pattern', 'verdict']) {
      assert.deepEqual(p[f], js[f], `case ${i} field ${f}`);
    }
    assert.deepEqual(p.gates, js.gates, `case ${i} gates`);
    for (const f of ['sl', 'tp2']) {
      assert.ok(Math.abs(p[f] - js[f]) <= 1e-9 * Math.max(1, Math.abs(js[f])), `case ${i} ${f}: ${p[f]} vs ${js[f]}`);
    }
  });
  // The fixture must exercise more than one verdict or the test proves little.
  assert.ok(Object.keys(verdicts).length >= 3, JSON.stringify(verdicts));
  console.log('verdict mix', verdicts, 'cases', cases.length);
});
