// Drawing tools module (DT): the parts that need no browser.
//   node --test tests/position-measure.test.cjs
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync(require('node:path').join(__dirname, '../protrader_mobile.html'), 'utf8');
const source = html.slice(html.indexOf('const DT = (() => {'), html.indexOf('   POSITION MANAGEMENT ON THE CHART'));

function setup(over = {}) {
  const context = vm.createContext(Object.assign({
    S: {sym: 'TEST', tf: '15m', dp: 2, balance: 10000}, TF_SEC: {'15m': 900},
    LIVE: {routing: () => false, acct: () => ({currency: 'USD'}), specLimits: () => null, riskAtStop: () => null},
    otSpec: () => ({lotStep: .01, minLot: .01, maxLot: 100}), otPnl: (side, e, s, v) => (s - e) * 100 * v,
    isMobile: () => false, window: {}, document: {getElementById: () => null, addEventListener() {}},
    localStorage: {getItem: () => null, setItem() {}}, console,
  }, over));
  vm.runInContext(source.slice(0, source.lastIndexOf('})();') + 5) + ';globalThis.dt = DT;', context);
  return context.dt;
}
const factory = kind => ({color: '#2962ff', width: 1, lineStyle: 'solid'});
const J = x => JSON.parse(JSON.stringify(x));   // objects cross the vm realm: compare by value

test('inline application JavaScript parses', () => {
  for (const script of html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)) new vm.Script(script[1]);
});
test('migration: the first engine\'s drawings become engine drawings, styles and flags kept', () => {
  const {migrateOld, normalize} = setup()._test;
  const h = migrateOld({id: 3, type: 'hline', color: '#F59E0B', pts: [{t: 100, p: 1.5}], name: 'Mirror', locked: true, hidden: true}, factory);
  assert.equal(h.kind, 'horizontal-line'); assert.deepEqual(J(h.points), [{time: 100, price: 1.5}]);
  assert.equal(h.style.color, '#F59E0B'); assert.equal(h.name, 'Mirror'); assert.equal(h.locked, true); assert.equal(h.hidden, true); assert.equal(h.id, 'v1-3');
  const t = migrateOld({id: 4, type: 'trend', pts: [{t: 100, p: 1}, {t: 200, p: 2}], style: 'dashed', width: 2.4, vis: {tf: ['1h', '4h']}}, factory);
  assert.equal(t.kind, 'trend-line'); assert.equal(t.style.lineStyle, 'dashed'); assert.equal(t.style.width, 2);
  assert.equal(t.visibility.hours.on, true); assert.equal(t.visibility.minutes.on, false); assert.equal(t.visibility.days.on, false);
  const l = migrateOld({id: 5, type: 'long', riskBudget: 250, pts: [{t: 100, p: 100}, {t: 300, p: 90}, {t: 300, p: 120}, {t: 300, p: 100}]}, factory);
  assert.equal(l.kind, 'long-position'); assert.deepEqual(J(l.points), [{time: 100, price: 100}, {time: 300, price: 100}]);
  assert.equal(l.style.stopLevel, 10); assert.equal(l.style.profitLevel, 20); assert.equal(l.riskBudget, 250);
  assert.equal(migrateOld({id: 6, type: 'nope', pts: [{t: 1, p: 1}]}, factory), null);
  assert.equal(migrateOld({id: 7, type: 'trend', pts: [{t: 1, p: 1}]}, factory), null, 'a two-point tool with one point is dropped');
  const n = normalize({A: [{id: 1, type: 'ray', pts: [{t: 1, p: 1}, {t: 2, p: 2}]}, {kind: 'rectangle', points: [], style: {}}], B: 'junk', C: []}, factory);
  assert.deepEqual(J(Object.keys(n)), ['A']); assert.deepEqual(J(n.A.map(d => d.kind)), ['ray', 'rectangle']);
});
test('colour helpers: hex and rgba with opacity round-trip', () => {
  const {parseColor, withAlpha} = setup()._test;
  assert.deepEqual(J(parseColor('#F23645')), {hex: '#f23645', alpha: 1});
  assert.deepEqual(J(parseColor('rgba(242, 54, 69, 0.5)')), {hex: '#f23645', alpha: .5});
  assert.equal(withAlpha('#f23645', .5), 'rgba(242, 54, 69, 0.5)'); assert.equal(withAlpha('rgba(242, 54, 69, 0.5)', 1), '#f23645');
  assert.deepEqual(J(parseColor('garbage')), {hex: '#2962ff', alpha: 1});
});
test('intervals map to the engine\'s TradingView-style strings', () => {
  const {TV_INTERVAL} = setup()._test;
  assert.deepEqual(J(TV_INTERVAL), {'1m': '1', '5m': '5', '15m': '15', '30m': '30', '1h': '60', '4h': '240', '1d': '1D', '1w': '1W'});
});
for (const kind of ['long-position', 'short-position']) {
  test(`${kind}: levels from the entry and the stop/target distances; budget sizing and R:R`, () => {
    const dt = setup(), sign = kind === 'long-position' ? 1 : -1;
    const d = {kind, points: [{time: 100, price: 100}, {time: 300, price: 100}], style: {stopLevel: 10, profitLevel: 20}, riskBudget: 100};
    const L = dt.positionLevels(d);
    assert.equal(L.entry, 100); assert.equal(L.sl, 100 - sign * 10); assert.equal(L.tp, 100 + sign * 20);
    const s = dt.positionStats(d);
    assert.equal(s.ratio, 2); assert.equal(s.lots, .1); assert.equal(s.risk, 100); assert.equal(s.reward, 200); assert.equal(s.currency, 'USD');
    d.style.stopLevel = 20; assert.equal(dt.positionStats(d).lots, .05); assert.equal(dt.positionStats(d).ratio, 1);
  });
}
test('position sizing rounds down to the lot step, respects min/max, and refuses without pricing', () => {
  const dt = setup(); const d = {kind: 'long-position', points: [{time: 1, price: 100}, {time: 2, price: 100}], style: {stopLevel: 10, profitLevel: 20}, riskBudget: 109};
  assert.equal(dt.positionStats(d).lots, .1);
  d.riskBudget = .1; assert.equal(dt.positionStats(d).lots, 0);
  d.riskBudget = 1e9; assert.equal(dt.positionStats(d).lots, 100);
  const noPx = setup({otPnl: () => null}); assert.equal(noPx.positionStats(d).lots, null);
  const live = setup({LIVE: {routing: () => true, acct: () => ({currency: 'EUR'}), specLimits: () => null, riskAtStop: () => 1000}});
  assert.equal(live.positionStats(d).lots, null, 'wrong/missing broker symbol must not use paper sizing');
  const live2 = setup({LIVE: {routing: () => true, acct: () => ({currency: 'EUR'}), specLimits: () => ({}), riskAtStop: () => 1000}});
  d.riskBudget = 100; assert.equal(live2.positionStats(d).lots, .1); assert.equal(live2.positionStats(d).currency, 'EUR');
});
test('a default stop distance is used when the drawing has none yet', () => {
  const dt = setup(); const d = {kind: 'short-position', points: [{time: 1, price: 100}, {time: 2, price: 95}], style: {}};
  const L = dt.positionLevels(d); assert.equal(L.stop, 5); assert.equal(L.profit, 5); assert.equal(L.sl, 105); assert.equal(L.tp, 95);
});
