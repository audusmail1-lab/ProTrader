const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync(require('node:path').join(__dirname, '../protrader_mobile.html'), 'utf8');
// otSpec, otQuote, otConv, otPnl and friends — a self-contained block with no
// top-level side effects, so it can run standalone in a sandboxed context.
const source = html.slice(html.indexOf('const otBook = {};'), html.indexOf('function otPipValue'));

function setup(pairPrices) {
  const context = vm.createContext({
    PAIR_MAP: { frxUSDJPY: { market: 'forex', label: 'USD/JPY' }, frxGBPJPY: { market: 'forex', label: 'GBP/JPY' } },
    CLASS_SPECS: { forex: { contractSize: 100000, minLot: 0.01, maxLot: 100, lotStep: 0.01, leverage: 100, minStopPts: 20 } },
    SPEC_OVERRIDE: {},
    LIVE: { routing: () => false },
    NEXUS: { staleMs: 12000 },
    pairPrices,
  });
  vm.runInContext(source, context);
  return context;
}

test('inline application JavaScript parses', () => {
  for (const script of html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)) new vm.Script(script[1]);
});

test('otConv refuses a stale cross rate by default, and otPnl reports unpriced (null) with it', () => {
  const sixHoursAgoPlus = Date.now() - (6 * 3600 * 1000 + 1000);
  const ctx = setup({ frxUSDJPY: { price: 150, ts: sixHoursAgoPlus } });
  assert.equal(ctx.otConv('frxGBPJPY'), null);
  assert.equal(ctx.otPnl('buy', 195, 196, 1, 'frxGBPJPY'), null);
});

test('otConv/otPnl accept a stale rate only when the caller opts in (allowStale)', () => {
  const sixHoursAgoPlus = Date.now() - (6 * 3600 * 1000 + 1000);
  const ctx = setup({ frxUSDJPY: { price: 150, ts: sixHoursAgoPlus } });
  assert.equal(ctx.otConv('frxGBPJPY', true), 1 / 150);
  const pnl = ctx.otPnl('buy', 195, 196, 1, 'frxGBPJPY', true);
  assert.ok(Number.isFinite(pnl) && pnl !== 0, 'a real, non-zero P&L — never a fabricated $0');
});

test('a closed position with no cross rate at all still gets null, not a guess', () => {
  const ctx = setup({});
  assert.equal(ctx.otConv('frxGBPJPY', true), null);
  assert.equal(ctx.otPnl('buy', 195, 196, 1, 'frxGBPJPY', true), null);
});

test('fresh rate is used as-is regardless of allowStale', () => {
  const ctx = setup({ frxUSDJPY: { price: 150, ts: Date.now() } });
  assert.equal(ctx.otConv('frxGBPJPY'), ctx.otConv('frxGBPJPY', true));
});
