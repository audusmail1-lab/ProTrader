/* Exercise actual terminal functions without DOM, feeds, account state or orders. */
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../protrader_mobile.html'),'utf8');
const start=source.indexOf('const ARIA_GATE_COUNT'),end=source.indexOf('function getPatternAlignment(',start);
assert.ok(start>=0&&end>start,'bounded ARIA core extraction');
const settings={dp:2,balance:10000,riskPct:1,newsWeek:false};
const scope=vm.createContext({S:settings});
vm.runInContext(source.slice(start,end)+'\nglobalThis.core={ariaGates,ariaVerdict,ariaEntry};',scope);
const {ariaGates,ariaVerdict,ariaEntry}=scope.core;
function fixture(n=240){
  const bars=Array.from({length:n},(_,i)=>{const close=100+i*.1;return{open:close-.05,high:close+.1,low:close-.1,close};});
  const closes=bars.map(b=>b.close),last=closes.at(-1),fill=x=>Array(n).fill(x);
  return{bars,closes,e20:fill(last-1),e50:fill(last-2),e200:fill(last-3),rsi:fill(60),macd:{line:fill(2),sig:fill(1)},stoch:{k:fill(40)},atr:fill(.2),pattern:'Fictional unit-test pattern'};
}
function gates(a){return ariaGates(a.bars,a.closes,a.e20,a.e50,a.e200,a.rsi,a.macd,a.stoch,a.atr,a.pattern,settings);}
function gate(result,name){const value=result.gates.find(g=>g.name===name);assert.ok(value,name);return value;}
function checkUnknown(a,name){const result=gates(a);assert.equal(gate(result,name).pass,null);assert.match(gate(result,name).detail,/Unavailable/);assert.ok(result.unavailable>0);assert.equal(result.available,false);assert.equal(result.percentage,null);assert.equal(result.score,result.gates.filter(g=>g.pass===true).length);return result;}

test('seven known matches stay seven of ten and show70percent; no missing-rule denominator shrink',()=>{
  const a=fixture();let result=gates(a);
  assert.equal(result.dir,'buy');assert.equal(result.total,10);assert.equal(result.score,9);assert.equal(result.unavailable,0);assert.equal(result.available,true);assert.equal(result.percentage,90);
  a.rsi[a.rsi.length-1]=80;a.pattern=null;result=gates(a);
  assert.equal(result.score,7);assert.equal(result.total,10);assert.equal(result.percentage,70);assert.equal(result.available,true);
  a.macd.sig=[];result=checkUnknown(a,'MACD Direction');assert.equal(result.score,6);assert.equal(result.total,10);
});

test('missing and invalid ATR remain unknown; zero is a known failure without replacement or levels',()=>{
  for(const value of [undefined,null,NaN,Infinity,-1]){const a=fixture();a.atr[a.atr.length-1]=value;checkUnknown(a,'ATR Band');assert.equal(ariaEntry(a.bars,a.closes,a.atr,'buy',{code:'TREND'},settings),null);}
  const a=fixture();a.atr=[];checkUnknown(a,'ATR Band');
  a.atr=Array(a.closes.length).fill(0);const result=gates(a);
  assert.equal(gate(result,'ATR Band').pass,false);assert.equal(result.score,8);assert.equal(result.unavailable,0);assert.equal(result.percentage,80);
  assert.equal(ariaEntry(a.bars,a.closes,a.atr,'buy',{code:'TREND'},settings),null);
});

test('MACD needs both finite aligned line and signal values; zero remains a valid observation',()=>{
  for(const field of ['line','sig'])for(const value of [undefined,null,NaN,Infinity]){const a=fixture();a.macd[field][a.closes.length-1]=value;checkUnknown(a,'MACD Direction');}
  const a=fixture();a.macd.sig.pop();checkUnknown(a,'MACD Direction');a.macd=null;checkUnknown(a,'MACD Direction');
  a.macd={line:Array(a.closes.length).fill(0),sig:Array(a.closes.length).fill(0)};
  assert.equal(gate(gates(a),'MACD Direction').pass,false);
});

test('stochastic null and nonfinite values cannot masquerade as opposing evidence or zero',()=>{
  for(const value of [undefined,null,NaN,Infinity,-1,101]){const a=fixture();a.stoch.k[a.closes.length-1]=value;checkUnknown(a,'Stochastic');}
  const a=fixture();a.stoch=null;checkUnknown(a,'Stochastic');a.stoch={k:Array(a.closes.length).fill(0)};
  assert.equal(gate(gates(a),'Stochastic').pass,true);
});

test('macro rule requires200 bars and an actual finite EMA200; no100-bar substitute',()=>{
  checkUnknown(fixture(199),'Macro Align');assert.equal(gate(gates(fixture(200)),'Macro Align').pass,true);
  for(const value of [undefined,null,NaN,Infinity,0]){const a=fixture();a.e200[a.closes.length-1]=value;checkUnknown(a,'Macro Align');}
  const a=fixture();a.e200=[];checkUnknown(a,'Macro Align');
});

test('direction requires50 bars and a strict stack; mixed or equal stacks are neutral without short levels',()=>{
  checkUnknown(fixture(49),'EMA Stack');assert.equal(gates(fixture(50)).dir,'buy');
  for(const variant of ['mixed','equal','missing']){
    const a=fixture(),n=a.closes.length,last=a.closes.at(-1);
    if(variant==='mixed'){a.e20[n-1]=last-1;a.e50[n-1]=last+1;}
    if(variant==='equal')a.e20[n-1]=last;
    if(variant==='missing')a.e50[n-1]=null;
    const result=gates(a);assert.equal(result.dir,'neutral');assert.equal(result.available,false);assert.equal(result.percentage,null);
    assert.equal(ariaEntry(a.bars,a.closes,a.atr,result.dir,{code:'TREND'},settings),null);
    assert.equal(ariaVerdict(9,{code:'TREND'},'CASE',result.dir,settings,result).v,'UNAVAILABLE');
  }
  const a=fixture(),n=a.closes.length;a.e20[n-1]=a.closes.at(-1)+1;a.e50[n-1]=a.closes.at(-1)+2;assert.equal(gates(a).dir,'sell');
});

test('forming candle is provisional; malformed bars stay unknown rather than passing',()=>{
  const a=fixture();assert.match(gate(gates(a),'Live Candle').detail,/forming/);
  a.bars.at(-1).high=0;checkUnknown(a,'Live Candle');checkUnknown(a,'Market Structure');
});

test('hard blocks outrank ten matches and unknown data; matches never authorize execution',()=>{
  const ready=gates(fixture()),unknown={...ready,available:false,unavailable:1,percentage:null};
  for(const result of [ready,unknown]){
    for(const code of ['DEAD_ZONE','FAKE_BREAK'])assert.equal(ariaVerdict(10,{code},'CASE','buy',settings,result).v,'OBSERVER');
    assert.equal(ariaVerdict(10,{code:'TREND'},'frxNAS100','sell',{...settings,newsWeek:true},result).v,'BLOCKED');
  }
  assert.equal(ariaVerdict(9,{code:'TREND'},'CASE','buy',settings,unknown).v,'UNAVAILABLE');
  for(const score of [NaN,Infinity,-1,11,8.5])assert.equal(ariaVerdict(score,{code:'TREND'},'CASE','buy',settings).v,'UNAVAILABLE');
  for(const score of [9,10]){const verdict=ariaVerdict(score,{code:'TREND'},'CASE','buy',settings,ready);assert.equal(verdict.v,'MATCHED');assert.match(verdict.msg,/CHECKLIST MATCH/);assert.doesNotMatch(verdict.msg,/EXECUTION READY|size normally|qualified setup/i);}
  assert.equal(ariaVerdict(8,{code:'TREND'},'CASE','buy',settings).v,'QUALIFIED');assert.match(ariaVerdict(8,{code:'TREND'},'CASE','buy',settings).msg,/CHECKLIST MATCH/);
});

test('known directional ATR produces levels; absent price or neutral direction never does',()=>{
  const a=fixture();const entry=ariaEntry(a.bars,a.closes,a.atr,'buy',{code:'TREND'},settings);
  assert.ok(entry.slLevel<entry.entry&&entry.tp2>entry.entry);assert.ok(Math.abs(entry.sl-.3)<1e-12);
  assert.equal(ariaEntry(a.bars,a.closes,a.atr,'neutral',{code:'TREND'},settings),null);
  a.closes[a.closes.length-1]=NaN;assert.equal(ariaEntry(a.bars,a.closes,a.atr,'buy',{code:'TREND'},settings),null);
});
