'use strict';
/*
 * Coverage for OT.checkStopOut() in protrader_mobile.html — the margin-call
 * safety net that force-closes the worst floating loser once the account's
 * margin level drops to/below STOP_OUT_LEVEL, so a paper account can't run
 * arbitrarily negative on an unattended losing position.
 *
 * protrader_mobile.html is a single-file, no-build front end: every script
 * lives inline in one <script> tag with module-level state (S, TR, TK,
 * pairPrices, ...), so this pulls the real source for that state plus the
 * order-ticket object (CLASS_SPECS ... OT) out of the shipped HTML and runs
 * it in a sandboxed VM context, rather than re-implementing the logic here.
 *
 * Run: node --test tests/
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const HTML_PATH = path.join(__dirname, '..', 'protrader_mobile.html');
const sleep = ms => new Promise(r => setTimeout(r, ms));

function sliceBetween(src, startMarker, endMarker) {
  const start = src.indexOf(startMarker);
  if (start === -1) throw new Error(`stop_out.test: start marker not found: ${startMarker}`);
  const end = src.indexOf(endMarker, start);
  if (end === -1) throw new Error(`stop_out.test: end marker not found: ${endMarker}`);
  return src.slice(start, end);
}

function loadOT() {
  const src = fs.readFileSync(HTML_PATH, 'utf8');

  // Plain state: S, PAIRS, PAIR_MAP, pairPrices — no DOM.
  const stateBlock = sliceBetween(src, 'const S = {', 'const pairPrices = {};') + 'const pairPrices = {};\n';

  // CLASS_SPECS ... end of the OT object (checkStopOut lives inside OT,
  // right after checkProtection). Stops before closeAllModals(), the next
  // top-level declaration after OT in the file.
  const otBlock = sliceBetween(src, 'const CLASS_SPECS = {', 'function closeAllModals');

  // NEXUS is defined later (feed-freshness bookkeeping); otQuote only reads
  // NEXUS.staleMs, so shim just that field. DOM/animation hooks OT.tick()
  // and friends touch are stubbed to no-ops — irrelevant to the money maths
  // and stop-out decision under test here.
  const shim = `
    const NEXUS = { staleMs: 12000 };
    let ws = null, CH;
    function showToast(){} function speak(){} function updateBalDisplay(){}
    function renderPortfolio(){} function updateGarden(){} function requestChartRedraw(){}
    const document = { getElementById: () => null, querySelectorAll: () => [],
      documentElement: { getAttribute: () => null } };
    const performance = { now: () => Date.now() };
    const requestAnimationFrame = () => {};
  `;

  const exportLine = `
    globalThis.__stopOut = { OT, TR, TK, S, pairPrices, otAccount, otPnl, STOP_OUT_LEVEL };
  `;

  const code = shim + stateBlock + '\n' + otBlock + '\n' + exportLine;
  const sandbox = { console, setTimeout, clearTimeout, setInterval: () => 0, clearInterval: () => {} };
  vm.createContext(sandbox);
  vm.runInContext(code, sandbox, { filename: 'protrader_mobile.html (extracted OT)' });
  return sandbox.__stopOut;
}

test('checkStopOut: does nothing while margin level stays above STOP_OUT_LEVEL', async () => {
  const m = loadOT();
  m.pairPrices.frxEURUSD = { price: 1.1000, ts: Date.now() };
  m.TR.positions.push({ id: 1, symbol: 'frxEURUSD', side: 'buy', entry: 1.1000, volume: 1, margin: 1100 });

  m.OT.checkStopOut();
  await sleep(250);

  assert.equal(m.TR.positions.length, 1);
});

test('checkStopOut: force-closes the position once margin level hits STOP_OUT_LEVEL', async () => {
  const m = loadOT();
  // Buy 10 lots EUR/USD at 1.1000, price craters to 1.0000: a $100,000
  // floating loss against $10,000 starting balance and $11,000 used margin
  // — equity/used well under 50%.
  m.pairPrices.frxEURUSD = { price: 1.0000, ts: Date.now() };
  m.TR.positions.push({ id: 1, symbol: 'frxEURUSD', side: 'buy', entry: 1.1000, volume: 10, margin: 11000 });
  assert.ok(m.otAccount().level <= m.STOP_OUT_LEVEL, 'fixture must actually breach the stop-out level');

  m.OT.checkStopOut();
  await sleep(250);

  assert.equal(m.TR.positions.length, 0);
  assert.equal(m.S.trades.length, 1);
  assert.equal(m.S.trades[0].reason, 'Stop out');
});

test('checkStopOut: closes the worst floating loser first when several positions are open', async () => {
  const m = loadOT();
  m.pairPrices.frxEURUSD = { price: 1.0000, ts: Date.now() };
  m.pairPrices.frxGBPUSD = { price: 1.1500, ts: Date.now() };
  m.TR.positions.push({ id: 1, symbol: 'frxGBPUSD', side: 'buy', entry: 1.1600, volume: 1, margin: 1150 });   // small loser
  m.TR.positions.push({ id: 2, symbol: 'frxEURUSD', side: 'buy', entry: 1.1000, volume: 10, margin: 11000 }); // big loser

  m.OT.checkStopOut();
  await sleep(250);

  assert.ok(!m.TR.positions.some(p => p.id === 2), 'the larger floating loss should be force-closed first');
});

test('checkStopOut: never force-closes on a partial equity figure (a position with no live quote)', async () => {
  const m = loadOT();
  m.pairPrices.frxEURUSD = { price: 1.0000, ts: Date.now() };
  m.TR.positions.push({ id: 1, symbol: 'frxEURUSD', side: 'buy', entry: 1.1000, volume: 10, margin: 11000 });
  // frxGBPJPY has no pairPrices entry at all -> otQuote() reports not ok,
  // so otAccount().unpriced > 0 and the account figure is only partial.
  m.TR.positions.push({ id: 2, symbol: 'frxGBPJPY', side: 'buy', entry: 150, volume: 1, margin: 1000 });

  m.OT.checkStopOut();
  await sleep(250);

  assert.equal(m.TR.positions.length, 2);
});
