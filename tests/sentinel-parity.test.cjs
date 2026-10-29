// Sentinel retains engine 7.1 independently of the newer UI checklist-v2.
// Compare its Python implementation with the frozen, provenance-pinned legacy
// JavaScript reference on identical candles; never migrate execution rules to
// satisfy current educational checklist behavior.
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
const currentSource = [
  cut('function calcEMA(', 'CHART — TradingView'),
  cut('const ARIA_LAWS', 'function renderARIA'),
  cut('const PATTERNS = [', 'function runPatternScanner'),
].join('\n');
const source = fs.readFileSync(path.join(__dirname,'fixtures/sentinel-engine-7.1.reference.js'),'utf8');
const provenance = JSON.parse(fs.readFileSync(path.join(__dirname,'fixtures/sentinel-engine-7.1.provenance.json'),'utf8'));
assert.equal(require('node:crypto').createHash('sha256').update(source).digest('hex'),provenance.fixtureSha256,'review any legacy fixture change against its recorded source commit');


// Deterministic random walk with regime changes, gaps and flat bars.
function makeCandles(seed, n, start, vol) {
  let s = seed >>> 0;
  const rnd = () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296);
  const out = []; let px = start, drift = 0, volMul = 1;
  for (let i = 0; i < n; i++) {
    if (i % 40 === 0) drift = (rnd() - 0.5) * vol * 0.6;
    if (i % 60 === 0) volMul = [0.25, 1, 1, 3][Math.floor(rnd() * 4)];   // volatility regimes
    const v = vol * volMul;
    const o = px, c = Math.max(1e-6, o + drift + (rnd() - 0.5) * v * 2);
    const flat = rnd() < 0.02;
    const h = flat ? o : Math.max(o, c) + rnd() * v;
    const l = flat ? o : Math.min(o, c) - rnd() * v;
    out.push({time: 1780000000 + i * 900, open: +o.toFixed(5), high: +h.toFixed(5),
              low: +l.toFixed(5), close: +(flat ? o : c).toFixed(5)});
    px = c;
  }
  return out;
}

function runJS(cdles, sym, hour, newsWeek, implementation=source) {
  class FixedDate extends Date { getUTCHours() { return hour; } }
  const S = {candles: cdles, sym, tf: '15m', dp: 5, balance: 10000, riskPct: 1, newsWeek, activePatterns: []};
  const ctx = vm.createContext({S, Date: FixedDate, Math, Number, JSON});
  vm.runInContext(implementation, ctx);
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
            wyckoff: wyck.phase, pattern: pat, verdict: v.v, sl: e?.slLevel ?? null, tp2: e?.tp2 ?? null};
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

test('Sentinel engine 7.1 matches its independent legacy JavaScript reference across 240 cases', () => {
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
  const gatePass = new Array(10).fill(0);
  cases.forEach((k, i) => {
    const js = JSON.parse(JSON.stringify(runJS(k.c, k.sym, k.hour, k.news))), p = py[i];
    verdicts[js.verdict] = (verdicts[js.verdict] || 0) + 1;
    js.gates.forEach((g, gi) => { if (g) gatePass[gi]++; });
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
  // Every gate must both pass and fail somewhere in the fixture, or a gate's
  // logic could differ between JS and Python without the test noticing.
  gatePass.forEach((c, gi) => assert.ok(c > 0 && c < cases.length, `gate ${gi} passed ${c}/${cases.length}`));
  console.log('gate passes', gatePass.join(' '));
  console.log('verdict mix', verdicts, 'cases', cases.length);
});

test('current ARIA checklist-v2 is explicitly separate from Sentinel legacy direction, score and execution status',()=>{
  assert.equal(provenance.engine,'7.1');assert.equal(provenance.executionModel,'7.2c');
  const first=cases[0],legacy=runJS(first.c,first.sym,first.hour,first.news),current=runJS(first.c,first.sym,first.hour,first.news,currentSource);
  assert.notEqual(current.score,legacy.score,'the version distinction must not hide the known independent rule behavior');
  const flat=Array.from({length:240},(_,i)=>({time:1780000000+i*900,open:100,high:100,low:100,close:100}));
  const old=runJS(flat,'R_50',14,false),next=runJS(flat,'R_50',14,false,currentSource);
  assert.equal(old.dir,'sell');assert.equal(next.dir,'neutral');assert.equal(next.sl,null);assert.equal(next.verdict,'UNAVAILABLE');
  assert.match(html,/ARIA_CHECKLIST_MODEL\s*=\s*['"]checklist-v2['"]/);
  const sentinel=html.slice(html.indexOf('const SENT = (() =>'),html.indexOf('A position opened from Sentinel'));
  assert.doesNotMatch(sentinel,/ARIA_GATE_COUNT/,'Sentinel scores must use their own recorded/server denominator');
  assert.match(sentinel,/Engine .*status.engine/);assert.match(sentinel,/Strategy .*status.model/);
});

test('Sentinel display uses recorded/server gate counts and identifies historical models without borrowing UI assumptions',()=>{
  const begin=html.indexOf('  function scoreText(record,'),end=html.indexOf('  function drift(t)',begin);
  assert.ok(begin>=0&&end>begin);const context=vm.createContext({esc:s=>String(s??'').replaceAll('<','&lt;').replaceAll('>','&gt;')});
  vm.runInContext(html.slice(begin,end)+'\nglobalThis.display={scoreText,modelText};',context);
  const {scoreText,modelText}=context.display;
  assert.equal(scoreText({score:7,gates:Array(9).fill(true),engine:'7.0',model:'fixed'}),'7/9');
  assert.equal(scoreText({score:8,engine:'7.1'},{engine:'7.1',gate_count:10}),'8/10');
  assert.equal(scoreText({score:7,engine:'7.0'},{engine:'7.1',gate_count:10}),'7/?');
  assert.equal(scoreText({score:7}),'7/?','unversioned historical data cannot borrow the current server denominator');
  assert.equal(scoreText({score:11,gates:Array(10).fill(true)}),'—/10');
  assert.equal(modelText({engine:'7.0',model:'fixed'}),'Engine 7.0 · strategy fixed');
  assert.match(modelText({model:'<unsafe>'}),/&lt;unsafe&gt;/);
});
