'use strict';
/*
 * Coverage for the order-ticket P&L/margin maths in protrader_mobile.html
 * (otPnl, otMarginFor, otConv, otSpec, otMoney, otAccount). These run the
 * real functions extracted from the shipped HTML — see extract_order_math.js
 * — not reimplementations, so a regression in the actual file fails here.
 *
 * Run: node --test tests/
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const { loadOrderMath } = require('./extract_order_math');

function fresh() {
  const m = loadOrderMath();
  // Each loadOrderMath() call re-runs the extracted source in a brand new
  // VM context, so PAIR_MAP/pairPrices/TR are pristine per test — no
  // leakage between cases despite the shared module-level state design.
  return m;
}

test('otSpec: forex majors get 100k contracts, 100:1 leverage, 1/10 pip pip-size at 5dp', () => {
  const m = fresh();
  const spec = m.otSpec('frxEURUSD');
  assert.equal(spec.contractSize, 100000);
  assert.equal(spec.leverage, 100);
  assert.equal(spec.dp, 5);
  assert.equal(spec.pip, 0.0001);
  assert.equal(spec.isForex, true);
});

test('otSpec: JPY-quoted forex pairs (3dp) use a 0.01 pip, not the 5dp default', () => {
  const m = fresh();
  const spec = m.otSpec('frxGBPJPY');
  assert.equal(spec.dp, 3);
  assert.equal(spec.pip, 0.01);
});

test('otSpec: SPEC_OVERRIDE wins over the market-class default (silver trades 5,000oz lots)', () => {
  const m = fresh();
  const spec = m.otSpec('frxXAGUSD');
  assert.equal(spec.contractSize, 5000);   // metal default is 100
  assert.equal(spec.leverage, 30);         // metal default is 50
});

test('otConv: USD-quoted pairs need no conversion', () => {
  const m = fresh();
  assert.equal(m.otConv('frxEURUSD'), 1);
  assert.equal(m.otConv('cryBTCUSD'), 1);   // crypto always quotes in USD
});

test('otConv: JPY-quoted cross needs the live USD/JPY rate and inverts it', () => {
  const m = fresh();
  m.pairPrices.frxUSDJPY = { price: 150, ts: Date.now() };
  assert.ok(Math.abs(m.otConv('frxGBPJPY') - 1 / 150) < 1e-9);
});

test('otConv: missing cross rate reports "no rate" (null) instead of guessing', () => {
  const m = fresh();
  assert.equal(m.otConv('frxGBPJPY'), null);   // frxUSDJPY never populated
});

test('otPnl: buy profits when price rises, by (exit-entry) * volume * contract size', () => {
  const m = fresh();
  const pnl = m.otPnl('buy', 1.1000, 1.1050, 1, 'frxEURUSD');
  assert.ok(Math.abs(pnl - 500) < 1e-9);
});

test('otPnl: sell profits when price falls (direction flips the sign)', () => {
  const m = fresh();
  const pnl = m.otPnl('sell', 1.1050, 1.1000, 1, 'frxEURUSD');
  assert.ok(Math.abs(pnl - 500) < 1e-9);
});

test('otPnl: scales with volume and applies the cross-currency conversion', () => {
  const m = fresh();
  m.pairPrices.frxUSDJPY = { price: 150, ts: Date.now() };
  const pnl = m.otPnl('buy', 150.00, 151.50, 2, 'frxGBPJPY');
  // (151.50 - 150.00) * 2 lots * 100,000 contract * (1/150 JPY->USD)
  const expected = 1.5 * 2 * 100000 * (1 / 150);
  assert.ok(Math.abs(pnl - expected) < 1e-6);
});

test('otPnl: refuses to guess without a conversion rate (returns null, not NaN)', () => {
  const m = fresh();
  const pnl = m.otPnl('buy', 150.00, 151.50, 1, 'frxGBPJPY');   // no frxUSDJPY seeded
  assert.equal(pnl, null);
});

test('otPnl: refuses to compute on a non-finite entry/exit (returns null, not NaN)', () => {
  const m = fresh();
  assert.equal(m.otPnl('buy', NaN, 1.1050, 1, 'frxEURUSD'), null);
  assert.equal(m.otPnl('buy', 1.1000, undefined, 1, 'frxEURUSD'), null);
});

test('otMarginFor: volume * contract size * price * conversion / leverage', () => {
  const m = fresh();
  const margin = m.otMarginFor('frxEURUSD', 1, 1.1000);
  assert.ok(Math.abs(margin - 1100) < 1e-9);   // 1 * 100000 * 1.1000 / 100
});

test('otMarginFor: null price or missing conversion rate yields null, never NaN', () => {
  const m = fresh();
  assert.equal(m.otMarginFor('frxEURUSD', 1, NaN), null);
  assert.equal(m.otMarginFor('frxGBPJPY', 1, 150), null);   // no USD/JPY cross seeded
});

test('otAccount: no open positions means zero used margin and a null margin level', () => {
  const m = fresh();
  const acct = m.otAccount();
  assert.equal(acct.used, 0);
  assert.equal(acct.upl, 0);
  assert.equal(acct.equity, m.S.balance);
  assert.equal(acct.free, m.S.balance);
  assert.equal(acct.level, null);   // used=0 would otherwise divide by zero
});

test('otAccount: sums margin used and floating P&L across open positions', () => {
  const m = fresh();
  m.pairPrices.frxEURUSD = { price: 1.1050, ts: Date.now() };
  m.TR.positions.push({ symbol: 'frxEURUSD', side: 'buy', entry: 1.1000, volume: 1, margin: 1100 });

  const acct = m.otAccount();
  // otQuote falls back to last price for both bid/ask with no live book.
  const expectedUpl = m.otPnl('buy', 1.1000, 1.1050, 1, 'frxEURUSD');
  assert.ok(Math.abs(acct.upl - expectedUpl) < 1e-9);
  assert.equal(acct.used, 1100);
  assert.ok(Math.abs(acct.equity - (m.S.balance + expectedUpl)) < 1e-9);
  assert.ok(Math.abs(acct.free - (acct.equity - 1100)) < 1e-9);
  assert.ok(Math.abs(acct.level - (acct.equity / 1100) * 100) < 1e-6);
});

test('otMoney: formats with thousands separators and a currency sign', () => {
  const m = fresh();
  assert.equal(m.otMoney(1234.5), '$1,234.50');
  assert.equal(m.otMoney(-1234.5), '-$1,234.50');
});

test('otMoney: never prints "-$0.00" for a sub-cent negative rounding artifact', () => {
  const m = fresh();
  assert.equal(m.otMoney(-0.001), '$0.00');
  assert.equal(m.otMoney(-0), '$0.00');
});

test('otMoney: non-finite input renders as an em dash, not "$NaN"', () => {
  const m = fresh();
  assert.equal(m.otMoney(NaN), '—');
  assert.equal(m.otMoney(null), '—');
});
