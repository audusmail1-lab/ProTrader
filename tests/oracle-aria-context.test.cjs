/* Regression against the actual terminal helpers, extracted without starting
 * the DOM, feeds, account bridge or trading execution. */
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const MTF=require('../static/mtf-analysis.js');
const source=fs.readFileSync(path.join(__dirname,'../protrader_mobile.html'),'utf8');
const AS_OF=1800000000;
const plain=value=>JSON.parse(JSON.stringify(value));
function between(from,to){const start=source.indexOf(from),end=source.indexOf(to,start);assert.ok(start>=0&&end>start,`${from} source boundary`);return source.slice(start,end);}
function clock(epoch){return class extends Date{constructor(...args){super(...(args.length?args:[epoch*1000]));}static now(){return epoch*1000;}};}
function environment(){
  const state={balance:10000,riskPct:1,dp:4,newsWeek:true,activePatterns:[{name:'Live-state sentinel'}]};
  const scope={S:state,Date:clock(AS_OF),ProTraderMTF:MTF,TF_SEC:{'1m':60,'5m':300,'15m':900,'1h':3600,'4h':14400}};
  vm.createContext(scope);
  vm.runInContext(
    between('function calcEMA(', 'let chartOffset = 0;')+'\n'+
    between('const ARIA_GATE_COUNT =', 'function renderARIA()')+'\n'+
    between('const PATTERNS = [','function runPatternScanSilent(')+'\n'+
    between('function oracleAriaOnSnapshot(', 'function oracleAdapter(')+'\n'+
    'globalThis.helpers={ariaMCC,ariaGates,ariaEntry,ariaVerdict,oracleAriaOnSnapshot,calcEMA,calcATR,calcRSI,calcMACD,calcStoch};',scope);
  return{scope,helpers:scope.helpers,state};
}
function candles(){return Array.from({length:240},(_,i)=>{const close=100+i*.07+.08*Math.sin(i/4),open=close-.05;return{time:AS_OF-(240-i)*900,open,high:close+.12,low:open-.12,close};});}
function inputs(helpers){
  const bars=candles(),closes=bars.map(b=>b.close);
  return{bars,closes,e20:helpers.calcEMA(closes,20),e50:helpers.calcEMA(closes,50),e200:helpers.calcEMA(closes,200),atr:helpers.calcATR(bars,14),rsi:helpers.calcRSI(closes),macd:helpers.calcMACD(closes),stoch:helpers.calcStoch(bars)};
}

test('ARIA optional settings preserve live default behavior when explicit settings match S',()=>{
  const{helpers,state}=environment(),a=inputs(helpers);
  const defaults=helpers.ariaMCC(a.bars,a.closes,a.e20,a.e50,a.atr),explicit=helpers.ariaMCC(a.bars,a.closes,a.e20,a.e50,a.atr,AS_OF);
  assert.deepEqual(plain(defaults),plain(explicit));
  const gateArgs=[a.bars,a.closes,a.e20,a.e50,a.e200,a.rsi,a.macd,a.stoch,a.atr,'Observed fixture pattern'];
  const gates=helpers.ariaGates(...gateArgs);assert.deepEqual(plain(gates),plain(helpers.ariaGates(...gateArgs,plain(state))));
  const entryArgs=[a.bars,a.closes,a.atr,gates.dir,defaults];
  assert.deepEqual(plain(helpers.ariaEntry(...entryArgs)),plain(helpers.ariaEntry(...entryArgs,plain(state))));
  for(const symbol of ['CASEUSD','frxNAS100']) for(const direction of ['buy','sell']) {
    const args=[8,defaults,symbol,direction];
    assert.deepEqual(plain(helpers.ariaVerdict(...args)),plain(helpers.ariaVerdict(...args,plain(state))));
  }
});

test('saved ARIA comparison uses only frozen settings/cutoff and never mutates the live pattern state',()=>{
  const{scope,helpers,state}=environment(),snapshot={id:'saved-context',symbol:'frxNAS100',asOf:AS_OF,settings:plain(state),series:{'15m':{status:'ready',source:'Clearly labelled fictional context fixture',candles:candles()}}};
  const h={timeframe:'15m'},beforeState=JSON.stringify(state),beforeSnapshot=JSON.stringify(snapshot);
  const first=plain(helpers.oracleAriaOnSnapshot(snapshot,h));
  assert.equal(first.available,true);assert.equal(first.snapshotId,snapshot.id);
  assert.equal(first.total,10);assert.equal(first.gates.length,10);
  assert.equal(first.gates.filter(g=>g.name==='Fibonacci Zone').length,1);
  assert.equal(first.score,first.gates.filter(g=>g.pass===true).length);
  assert.equal(first.percentage,Math.round(first.score/10*100));
  assert.equal(first.closedAt,AS_OF);assert.equal(JSON.stringify(state),beforeState);
  assert.equal(JSON.stringify(snapshot),beforeSnapshot);
  scope.S=new Proxy({}, {get(){throw Error('Saved ARIA comparison read live S');},set(){throw Error('Saved ARIA comparison mutated live S');}});
  scope.Date=clock(AS_OF+15*3600);
  const later=plain(helpers.oracleAriaOnSnapshot(snapshot,h));
  assert.deepEqual(later,first,'Changed live state or wall-clock session cannot rewrite the saved comparison');
});


test('pattern agreement accepts only a matching recent completion on the supplied candles',()=>{
  const bars=candles();let detectedAt=bars.length-4,fit=90,orientation='bull';
  const scope={S:new Proxy({}, {get(){throw Error('Explicit candles must not read live S');}}),
    PATTERNS:[{name:'Fixture completion',get dir(){return orientation;},detect:(items,index)=>{assert.equal(items,bars);return index===detectedAt?{conf:fit,i:detectedAt}:null;}}]};
  vm.createContext(scope);
  vm.runInContext(between('const ARIA_GATE_COUNT =','function ariaMCC(')+'\n'+between('function getPatternAlignment(','function renderARIA()'),scope);
  assert.equal(scope.getPatternAlignment('buy',bars),null,'A pattern four bars back is too old');
  detectedAt=bars.length-3;assert.equal(scope.getPatternAlignment('buy',bars),'Fixture completion');
  fit=74;assert.equal(scope.getPatternAlignment('buy',bars),null,'A weak fit cannot pass');
  fit=75;orientation='bear';assert.equal(scope.getPatternAlignment('buy',bars),null,'Opposite patterns cannot pass');
  assert.equal(scope.getPatternAlignment('sell',bars),'Fixture completion');
  assert.equal(scope.getPatternAlignment('neutral',bars),null);
});
