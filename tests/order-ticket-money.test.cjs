// Order ticket money maths (otSpec/otConv/otPnl/otPipValue/otMarginFor/otAccount/riskLots):
// the P&L, margin and position-sizing formulas every ticket validation and fill relies on.
//   node --test tests/order-ticket-money.test.cjs
const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const html=fs.readFileSync(require('node:path').join(__dirname,'../protrader_mobile.html'),'utf8');
const source=html.slice(html.indexOf('const CLASS_SPECS = {'),html.lastIndexOf('/* ═',html.indexOf('MT5 LIVE BRIDGE')))
  +html.slice(html.indexOf('function riskLots(id, entry, sl, balance, budget) {'),html.indexOf('const CHECK_UI = { expanded: false };'));

function setup(over={}){
  const PAIR_MAP={
    frxEURUSD:{label:'EUR/USD',market:'forex',dp:5},
    frxUSDJPY:{label:'USD/JPY',market:'forex',dp:3},
    frxGBPJPY:{label:'GBP/JPY',market:'forex',dp:3},
    frxGBPUSD:{label:'GBP/USD',market:'forex',dp:5},
    frxUSDMXN:{label:'USD/MXN',market:'forex',dp:4},
    frxXAUUSD:{label:'XAU/USD',market:'metal',dp:2},
    frxXAGUSD:{label:'XAG/USD',market:'metal',dp:4},
    OTC_FTSE:{label:'UK 100',market:'index',dp:2,ccy:'GBP'},
    OTC_HSI:{label:'Hong Kong 50',market:'index',dp:2,ccy:'HKD'},
  };
  const context=vm.createContext(Object.assign({
    PAIR_MAP, LIVE:{routing:()=>false}, NEXUS:{staleMs:12000},
    pairPrices:{}, S:{balance:10000,riskPct:1}, console,
  },over));
  const positions=JSON.stringify(over.positions||[]);
  vm.runInContext(`${source};TR.positions=${positions};globalThis.X={otSpec,otConv,otPnl,otPipValue,otMarginFor,otAccount,riskLots};`,context);
  return context.X;
}
const fresh=px=>({price:px,ts:Date.now()});
const stale=px=>({price:px,ts:Date.now()-7*3600*1000});

test('inline application JavaScript parses', () => {
  for (const script of html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)) new vm.Script(script[1]);
});

test('otSpec: pip size follows decimal places, metal override applies, index ccy carries through', () => {
  const X=setup();
  assert.equal(X.otSpec('frxEURUSD').pip, 0.0001);     // 5dp major
  assert.equal(X.otSpec('frxUSDJPY').pip, 0.01);        // 3dp JPY cross
  assert.equal(X.otSpec('frxUSDMXN').pip, 0.001);       // 4dp MXN/PLN
  const xag=X.otSpec('frxXAGUSD');
  assert.equal(xag.contractSize, 5000); assert.equal(xag.leverage, 30);   // silver override
  assert.equal(X.otSpec('frxXAUUSD').contractSize, 100);                  // unoverridden metal default
  assert.equal(X.otSpec('OTC_FTSE').isForex, false);
});

test('otConv: USD-quoted pairs need no conversion; crosses resolve through a live rate; stale or missing rates refuse', () => {
  const X=setup({pairPrices:{frxUSDJPY:fresh(154.20), frxGBPUSD:fresh(1.2710)}});
  assert.equal(X.otConv('frxEURUSD'), 1);                       // quoted in USD
  assert.equal(X.otConv('frxUSDJPY'), 1/154.20);                 // JPY cross inverts
  assert.equal(X.otConv('frxGBPJPY'), 1/154.20);                 // any xxx/JPY pair uses the same cross
  assert.equal(X.otConv('frxGBPUSD'), 1);                        // GBP/USD itself is already USD-quoted
  assert.equal(X.otConv('OTC_FTSE'), 1.2710);                    // GBP-denominated index via GBP/USD
  assert.equal(X.otConv('OTC_HSI'), 1/7.80);                     // HKD peg, no live feed needed
  assert.equal(setup({pairPrices:{}}).otConv('frxUSDJPY'), null);              // no rate at all
  assert.equal(setup({pairPrices:{frxUSDJPY:stale(154.20)}}).otConv('frxUSDJPY'), null); // rate older than 6h
});

test('otPnl: direction-aware, converts to account currency, refuses without a rate or a finite price', () => {
  const X=setup();
  assert.equal(X.otPnl('buy', 1.1000, 1.1050, 2, 'frxEURUSD'), (1.1050-1.1000)*1*2*100000*1);
  assert.equal(X.otPnl('sell', 1.1000, 1.1050, 2, 'frxEURUSD'), (1.1050-1.1000)*-1*2*100000*1);
  assert.equal(X.otPnl('buy', 1.1, NaN, 1, 'frxEURUSD'), null);
  const noRate=setup({pairPrices:{}});
  assert.equal(noRate.otPnl('buy', 154, 155, 1, 'frxUSDJPY'), null);
});

test('otPipValue and otMarginFor scale with volume, contract size and conversion; both refuse without a rate', () => {
  const X=setup({pairPrices:{frxUSDJPY:fresh(154.20)}});
  const spot=X.otSpec('frxEURUSD');
  assert.equal(X.otPipValue('frxEURUSD', 2), spot.pip*2*spot.contractSize*1);
  const conv=1/154.20;
  assert.ok(Math.abs(X.otPipValue('frxUSDJPY', 1) - X.otSpec('frxUSDJPY').pip*1*100000*conv) < 1e-9);
  assert.equal(X.otMarginFor('frxEURUSD', 1, 1.10), (1*100000*1.10*1)/100);     // forex 100:1 leverage
  assert.equal(X.otMarginFor('frxXAGUSD', 1, 33.20), (1*5000*33.20*1)/30);      // silver 5000oz lot, 30:1
  const noRate=setup({pairPrices:{}});
  assert.equal(noRate.otMarginFor('frxUSDJPY', 1, 154), null);
  assert.equal(noRate.otPipValue('frxUSDJPY', 1), null);
});

test('otAccount: equity follows unrealized P&L, free margin nets used, level is null with nothing open, unpriced flags a gap', () => {
  const X=setup({
    pairPrices:{frxEURUSD:fresh(1.1050)},
    positions:[{symbol:'frxEURUSD', side:'buy', entry:1.1000, volume:1, margin:1100}],
  });
  const a=X.otAccount();
  const upl=(1.1050-1.1000)*1*1*100000*1;
  assert.ok(Math.abs(a.used-1100)<1e-9); assert.ok(Math.abs(a.upl-upl)<1e-9);
  assert.ok(Math.abs(a.equity-(10000+upl))<1e-9); assert.ok(Math.abs(a.free-(a.equity-1100))<1e-9);
  assert.equal(a.unpriced, 0);
  assert.ok(Math.abs(a.level-(a.equity/1100*100))<1e-9);

  const empty=setup({positions:[]}).otAccount();
  assert.equal(empty.used, 0); assert.equal(empty.equity, 10000); assert.equal(empty.level, null);

  const gap=setup({
    pairPrices:{},
    positions:[{symbol:'frxUSDJPY', side:'buy', entry:154, volume:1, margin:500}],
  }).otAccount();
  assert.equal(gap.unpriced, 1);   // no live quote for the one open position: equity is a partial figure
});

test('riskLots: sizes to the risk budget, rounds down to the lot step, clamps to maxLot, refuses a zero-distance stop', () => {
  const X=setup({S:{balance:10000, riskPct:1}});
  const r=X.riskLots('frxEURUSD', 1.1000, 1.0950, 10000);   // 50 pip stop, $100 budget (1%)
  const pipValuePerLot=X.otPipValue('frxEURUSD', 1);
  const riskPerLot=(0.0050/0.0001)*pipValuePerLot;
  assert.ok(Math.abs(r.riskPerLot-riskPerLot)<1e-6);
  assert.ok(Math.abs(r.lots-(Math.floor((100/riskPerLot)/0.01+1e-9)*0.01))<1e-9);
  assert.equal(r.min, 0.01);
  assert.equal(X.riskLots('frxEURUSD', 1.1000, 1.1000, 10000), null);     // zero distance: no size is defined
  const huge=X.riskLots('frxEURUSD', 1.1000, 1.0950, 10000, 1e9);         // budget far beyond maxLot
  assert.equal(huge.lots, X.otSpec('frxEURUSD').maxLot);
});
