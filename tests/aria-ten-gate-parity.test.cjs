/* Desktop v7.1 golden cases: no installed desktop path is needed at runtime.
 * Recorded from the desktop constants, ariaGates and ariaFib on 2026-10-19.
 * Extracted baseline SHA256: ef83d554a7ee73db98a4c0f6d681367a316c83fac7939f04faae047d84c6f26c.
 */
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const html=fs.readFileSync(path.join(__dirname,'../protrader_mobile.html'),'utf8');
const start=html.indexOf('const ARIA_GATE_COUNT'),patternStart=html.indexOf('function getPatternAlignment(',start);
const patternEnd=html.indexOf('function renderARIA()',patternStart);
assert.ok(start>=0&&patternStart>start&&patternEnd>patternStart,'bounded ten-gate core extraction');
const S={dp:2,balance:10000,riskPct:1,newsWeek:false,candles:[]};
const scope=vm.createContext({S,PATTERNS:[]});
vm.runInContext(html.slice(start,patternStart)+html.slice(patternStart,patternEnd)+'\nglobalThis.core={ariaFib,ariaGates,ariaVerdict,getPatternAlignment};',scope);
const {ariaFib,ariaGates,ariaVerdict,getPatternAlignment}=scope.core;
function fixture({dir='buy',age=4,depth=.5,leg=20,atr=2}={}){
  const n=240,L=100,H=L+leg,ext=230,touch=n-1-age;
  const bars=Array.from({length:n},(_,i)=>({time:i*900,open:L+leg*.4,high:L+leg*.5,low:L+leg*.35,close:L+leg*.45}));
  bars[200]={...bars[200],open:L+leg*.1,high:L+leg*.2,low:L,close:L+leg*.15};
  bars[ext]={...bars[ext],open:H-leg*.08,high:H,low:H-leg*.1,close:H-leg*.025};
  const pullback=H-leg*depth;
  for(let i=ext+1;i<n;i++){
    const low=i<=touch?H-leg*.1-(H-leg*.1-pullback)*(i-ext)/(touch-ext):pullback+(i-touch)*leg*.035;
    bars[i]={time:i*900,open:low+leg*.025,high:low+leg*.1,low,close:low+leg*.05};
  }
  if(dir==='sell')for(const c of bars){const {open,high,low,close}=c;c.open=300-open;c.high=300-low;c.low=300-high;c.close=300-close;}
  const closes=bars.map(c=>c.close),last=closes.at(-1),fill=x=>Array(n).fill(x),sign=dir==='buy'?1:-1;
  return{bars,closes,e20:fill(last-sign),e50:fill(last-sign*3),e200:fill(last-sign*10),rsi:fill(dir==='buy'?60:40),
    macd:{line:fill(sign*2),sig:fill(sign)},stoch:{k:fill(dir==='buy'?40:60)},atr:fill(atr),pattern:'Fixture recent pattern',dir};
}
function gates(a){return ariaGates(a.bars,a.closes,a.e20,a.e50,a.e200,a.rsi,a.macd,a.stoch,a.atr,a.pattern,S);}
function gate(a,name){const result=gates(a).gates.find(g=>g.name===name);assert.ok(result,name);return result;}
const NAMES=['EMA Stack','RSI Momentum','MACD Direction','Market Structure','Live Candle','ATR Band','Macro Align','Stochastic','Pattern Gate','Fibonacci Zone'];

test('complete valid bullish and bearish cases retain the desktop ten-gate baseline',()=>{
  // Frozen desktop outputs for these deterministic fixtures, verified when added.
  const cases=[
    {options:{dir:'buy'},pass:[true,true,true,true,true,true,true,true,true,true]},
    {options:{dir:'sell'},pass:[true,true,true,true,true,true,true,true,true,true]},
    {options:{dir:'buy',age:6},pass:[true,true,true,true,true,true,true,true,true,false]},
    {options:{dir:'sell',depth:.8},pass:[true,true,true,true,true,true,true,true,true,false]},
    {options:{dir:'buy'},opposed:true,pass:[true,false,false,true,true,false,false,false,false,true]},
    {options:{dir:'sell'},opposed:true,pass:[true,false,false,true,true,false,false,false,false,true]}
  ];
  for(const c of cases){
    const a=fixture(c.options);
    if(c.opposed){
      const n=a.closes.length;a.rsi[n-1]=80;a.macd.line[n-1]=0;a.macd.sig[n-1]=0;a.stoch.k[n-1]=50;
      a.e200[n-1]=a.closes[n-1]+(a.dir==='buy'?1:-1);a.atr[n-1]=4;a.pattern=null;
    }
    const result=gates(a);
    assert.deepEqual(Array.from(result.gates,g=>g.name),NAMES);
    assert.deepEqual(Array.from(result.gates,g=>g.pass),c.pass,JSON.stringify(c.options));
    assert.equal(result.dir,c.options.dir);assert.equal(result.score,c.pass.filter(Boolean).length);
    assert.equal(result.total,10);assert.equal(result.available,true);assert.equal(result.percentage,result.score*10);
  }
});

test('Fibonacci distinguishes both directions, shallow/deep retraces, old touches and small swings',()=>{
  for(const dir of ['buy','sell']){
    for(const [options,expected] of [[{},true],[{age:5},true],[{age:6},false],[{depth:.2},false],[{depth:.8},false],[{leg:5,atr:2},false]]){
      const a=fixture({dir,...options}),result=ariaFib(a.bars,a.atr,dir);
      assert.equal(result.pass,expected,JSON.stringify({dir,...options}));
      if(expected)assert.ok(Math.abs(result.r-.5)<1e-12);
    }
  }
});

test('Fibonacci requires actual directional candles and ATR; zero ATR fails without invented values',()=>{
  for(const dir of ['neutral',undefined,'other']){const a=fixture();assert.equal(ariaFib(a.bars,a.atr,dir).pass,null);}
  for(const value of [undefined,null,NaN,Infinity,-1]){const a=fixture();a.atr[a.atr.length-1]=value;assert.equal(ariaFib(a.bars,a.atr,'buy').pass,null);assert.equal(gates(a).percentage,null);}
  const short=fixture();assert.equal(ariaFib(short.bars.slice(-29),short.atr.slice(-29),'buy').pass,null);
  const malformed=fixture();malformed.bars[200].low=NaN;assert.equal(ariaFib(malformed.bars,malformed.atr,'buy').pass,null);
  const zero=fixture({atr:0});assert.equal(ariaFib(zero.bars,zero.atr,'buy').pass,false);assert.equal(gate(zero,'Fibonacci Zone').pass,false);
});

function setRatio(a,ratio){
  // The last100 observations sum to100, giving an exact unit mean including current ATR.
  a.atr.fill(1);a.atr[a.atr.length-2]=2-ratio;a.atr[a.atr.length-1]=ratio;
}
test('ATR Band includes0.6 and1.8 but rejects values immediately outside the desktop band',()=>{
  for(const [ratio,pass] of [[.599999,false],[.6,true],[1,true],[1.8,true],[1.800001,false]]){
    const a=fixture();setRatio(a,ratio);assert.equal(gate(a,'ATR Band').pass,pass,String(ratio));
  }
  const positiveOnly=fixture();positiveOnly.atr.fill(0);positiveOnly.atr[positiveOnly.atr.length-1]=1;
  assert.equal(gate(positiveOnly,'ATR Band').pass,true,'Known zeros are excluded from the positive-value mean');
  const zero=fixture({atr:0});assert.equal(gate(zero,'ATR Band').pass,false);
});

test('ATR Band cannot present missing or invalid recent history as a100-observation average',()=>{
  for(const value of [undefined,null,NaN,Infinity,-1]){
    const a=fixture();a.atr[a.atr.length-100]=value;
    assert.equal(gate(a,'ATR Band').pass,null);assert.equal(gates(a).percentage,null);
  }
  const short=fixture();short.atr=Array(99).fill(2);assert.equal(gate(short,'ATR Band').pass,null);
  const oldMissing=fixture();oldMissing.atr[oldMissing.atr.length-101]=null;assert.equal(gate(oldMissing,'ATR Band').pass,true);
});

test('only aligned patterns completed in the latest three bars can satisfy Pattern Gate',()=>{
  const a=fixture(),n=a.bars.length;S.candles=a.bars;
  for(const dir of ['buy','sell']){
    const want=dir==='buy'?'bull':'bear',opposite=dir==='buy'?'bear':'bull';
    for(const [index,conf,expected] of [[n-1,75,'Recent'],[n-3,90,'Recent'],[n-4,99,null],[n-1,74,null]]){
      scope.PATTERNS=[{name:'Recent',dir:want,detect:(_bars,i)=>i===index?{conf,i:index}:null},{name:'Wrong side',dir:opposite,detect:()=>({conf:100,i:n-1})}];
      assert.equal(getPatternAlignment(dir,a.bars),expected,`${dir} index${index} confidence${conf}`);
    }
  }
  scope.PATTERNS=[{name:'Bearish',dir:'bear',detect:()=>({conf:99,i:n-1})}];
  assert.equal(getPatternAlignment('neutral',a.bars),null);
});

test('desktop thresholds retain safer preview wording and hard-block priority',()=>{
  const known=gates(fixture());
  for(const [score,state] of [[5,'OBSERVER'],[6,'WAITING'],[7,'WAITING'],[8,'QUALIFIED'],[9,'MATCHED'],[10,'MATCHED']]){
    const result=ariaVerdict(score,{code:'TREND'},'FIXTURE','buy',S,known);
    assert.equal(result.v,state);assert.doesNotMatch(result.msg,/EXECUTION READY|size normally/i);
  }
  for(const code of ['DEAD_ZONE','FAKE_BREAK'])assert.equal(ariaVerdict(10,{code},'FIXTURE','buy',S,known).v,'OBSERVER');
  assert.equal(ariaVerdict(10,{code:'TREND'},'frxNAS100','sell',{...S,newsWeek:true},known).v,'BLOCKED');
});
