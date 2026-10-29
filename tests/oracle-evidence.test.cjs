const{test}=require('node:test');
const assert=require('node:assert/strict');
const Evidence=require('../static/oracle-evidence.js');
const CUTOFF=1800000000.25,SECONDS={'1m':60,'5m':300,'15m':900,'1h':3600,'4h':14400,'1d':86400};
const clone=x=>JSON.parse(JSON.stringify(x));
function candles(tf,direction=1,count=60,end=CUTOFF){
  const seconds=SECONDS[tf],boundary=Math.floor(end/seconds)*seconds;
  return Array.from({length:count},(_,i)=>{const close=200+direction*i*.4,open=close-direction*.2;return{time:boundary-(count-i)*seconds,open,high:Math.max(open,close)+.1,low:Math.min(open,close)-.1,close};});
}
function snapshot(){return{version:1,id:'snapshot-evidence-test',symbol:'R_100',label:'Private label must not be sent',provider:'Deriv',asOf:CUTOFF,capturedAt:CUTOFF+2,dataReference:'fnv1a32-deadbeef',series:{'15m':{status:'ready',source:'Deriv',capturedAt:CUTOFF+1,candles:candles('15m',1)},'1h':{status:'ready',source:'Deriv',capturedAt:CUTOFF+2,candles:candles('1h',-1)}}};}
function failure(s,code){const result=Evidence.extract(s,'15m');assert.equal(result.available,false);assert.ok(result.unknowns.some(u=>u.code===code),JSON.stringify(result.unknowns));return result;}

test('extracts independent numeric primary and higher facts with attributable source and pinned cutoff',()=>{
  const s=snapshot(),before=JSON.stringify(s),r=Evidence.extract(s,'15m');
  assert.equal(r.available,true);assert.equal(r.asOf,CUTOFF);assert.equal(r.capturedAt,CUTOFF+2);
  assert.equal(r.snapshotId,s.id);assert.equal(r.symbol,s.symbol);assert.equal(r.dataReference,s.dataReference);
  assert.equal(r.timeframe,'15m');assert.equal(r.higherTimeframe,'1h');
  assert.equal(r.frames['15m'].lastClose,223.6);assert.equal(r.frames['1h'].lastClose,176.4);
  assert.ok(r.frames['15m'].closeDisplacement20>0);assert.ok(r.frames['1h'].closeDisplacement20<0);
  for(const tf of ['15m','1h']){
    const bars=s.series[tf].candles,prior=bars.slice(-21,-1),f=r.frames[tf];
    assert.equal(f.closedAt,Math.floor(CUTOFF/SECONDS[tf])*SECONDS[tf]);
    assert.equal(f.prior20Low,Math.min(...prior.map(b=>b.low)));assert.equal(f.prior20High,Math.max(...prior.map(b=>b.high)));
    assert.equal(f.closedBars,60);assert.match(f.source,new RegExp(`Deriv.*${tf}`));
    assert.ok(f.refs.every(ref=>ref.startsWith(s.id+':'+tf+':')));
  }
  assert.equal(r.facts.length,2);assert.equal(JSON.stringify(s),before);
  assert.match(r.scope,/no execution signal or probability/i);
  assert.ok(r.notAssessed.includes('news'));assert.ok(r.notAssessed.includes('order flow'));
});

test('extreme forming and future prices are excluded rather than becoming model context',()=>{
  const s=snapshot(),baseline=Evidence.extract(s,'15m');
  for(const tf of ['15m','1h']){
    const first=Math.floor(CUTOFF/SECONDS[tf])*SECONDS[tf];
    s.series[tf].candles.push({time:first,open:123456789,high:987654321,low:.0001,close:876543210},
      {time:first+SECONDS[tf],open:123456789,high:987654321,low:.0001,close:876543210});
  }
  const r=Evidence.extract(s,'15m');assert.deepEqual(r,baseline);
  assert.doesNotMatch(JSON.stringify(r),/123456789|987654321|876543210/);
});

test('does not expose raw bars, ARIA outputs, account details, user prose, errors or cached analysis',()=>{
  const s=snapshot(),baseline=Evidence.extract(s,'15m');
  s.account={balance:7654321,token:'ACCOUNT_SECRET'};s.quote={bid:666.66,ask:777.77};s.settings={account:'PRIVATE_SETTINGS'};
  s.aria={score:9,verdict:'EXEC_READY',levels:{entry:999.99},prose:'ARIA_ENDORSEMENT'};
  s.hypothesis={reasoning:'USER_THESIS_SECRET',invalidation:'USER_PROSE_SECRET'};
  s.lessonRef={reflection:'PRIVATE_STUDENT_REFLECTION'};
  Object.defineProperty(s,'analysis',{get(){throw Error('Unvalidated cached analysis was read');}});
  for(const row of Object.values(s.series)){
    row.error='UPSTREAM_ERROR_PROSE';
    for(const bar of row.candles)Object.defineProperty(bar,'note',{get(){throw Error('User-authored candle note was read');}});
  }
  const r=Evidence.extract(s,'15m');assert.deepEqual(r,baseline);
  const json=JSON.stringify(r);
  for(const secret of ['ACCOUNT_SECRET','PRIVATE_SETTINGS','ARIA_ENDORSEMENT','USER_THESIS_SECRET','USER_PROSE_SECRET','PRIVATE_STUDENT_REFLECTION','UPSTREAM_ERROR_PROSE','Private label','EXEC_READY','7654321','999.99'])assert.equal(json.includes(secret),false,secret);
  function inspect(value){if(!value||typeof value!=='object')return;for(const key of Object.keys(value)){assert.ok(!['candles','bars','account','settings','aria','quote','analysis','hypothesis','levels','score','verdict'].includes(key),key);inspect(value[key]);}}
  inspect(r);
});

test('sanitized source labels are constructed from capture metadata and never echo arbitrary prose',()=>{
  const s=snapshot();for(const tf of ['15m','1h'])s.series[tf].source=`Deriv · independently requested ${tf} history`;
  assert.equal(Evidence.extract(s,'15m').available,true);
  s.series['15m'].source='Deriv · INJECTED_SOURCE_INSTRUCTION';
  const bad=failure(s,'history-source');assert.doesNotMatch(JSON.stringify(bad),/INJECTED_SOURCE_INSTRUCTION/);
  s.series['15m'].source='Yahoo';failure(s,'history-source');
  s.provider='CUSTOM_PROVIDER_PROSE';const unsupported=failure(s,'source-provider');assert.doesNotMatch(JSON.stringify(unsupported),/CUSTOM_PROVIDER_PROSE/);
  const yahoo=snapshot();yahoo.provider='Yahoo';for(const row of Object.values(yahoo.series))row.source='Yahoo';
  assert.match(Evidence.extract(yahoo,'15m').frames['15m'].source,/Yahoo Finance/);
});

test('invalid OHLC, missing context, insufficient, stale and incompatible interval data remain honest unknowns',()=>{
  const checks=[
    ['history-unavailable',s=>{s.series['1h'].status='unavailable';s.series['1h'].error='Do not echo this arbitrary prose';}],
    ['history-insufficient',s=>{s.series['15m'].candles=s.series['15m'].candles.slice(-29);}],
    ['history-insufficient',s=>{s.series['15m'].candles=candles('15m').map((b,i)=>({...b,time:1800000000+i*900}));}],
    ['history-stale',s=>{s.series['15m'].candles=candles('15m',1,60,CUTOFF-86400);}],
    ['history-integrity',s=>{s.series['15m'].candles.at(-5).close=NaN;}],
    ['history-integrity',s=>{s.series['15m'].candles.at(-5).low=-1;}],
    ['history-integrity',s=>{s.series['15m'].candles.at(-5).high=1;}],
    ['interval-integrity',s=>{s.series['15m'].candles=candles('1m');}],
    ['interval-integrity',s=>{s.series['15m'].candles[10].time=s.series['15m'].candles[9].time;}],
    ['interval-integrity',s=>{s.series['15m'].candles[10].time+=1;}],
    ['history-cutoff',s=>{s.series['15m'].capturedAt=CUTOFF-1;}],
    ['history-cutoff',s=>{s.series['15m'].capturedAt=CUTOFF+100;}],
    ['history-source',s=>{s.series['15m'].source='';}]
  ];
  for(const[code,change]of checks){const s=snapshot();change(s);const r=failure(s,code);assert.ok(r.unknowns.every(u=>u.essential));}
  const partial=snapshot();partial.series['1h'].status='unavailable';const r=failure(partial,'history-unavailable');
  assert.ok(r.frames['15m']);assert.equal(r.frames['1h'],undefined);assert.equal(r.facts.length,1);
  assert.doesNotMatch(JSON.stringify(r),/Do not echo/);
});

test('a saved forming candle cannot become completed evidence through later wall time or a changed cutoff',()=>{
  const s=snapshot(),initial=Evidence.extract(s,'15m'),now=Date.now;
  try{Date.now=()=>CUTOFF*1000+86400000;assert.deepEqual(Evidence.extract(s,'15m'),initial);}finally{Date.now=now;}
  s.asOf+=86400;failure(s,'snapshot-cutoff');
});

test('malformed snapshot identities and unsupported horizons return bounded failures without copying the input',()=>{
  assert.equal(Evidence.extract(null,'15m').available,false);
  assert.equal(Evidence.extract(snapshot(),'1d').available,false);
  assert.equal(Evidence.extract(snapshot(),'USER_TIMEFRAME_PROSE').timeframe,null);
  const s=snapshot();s.id='PRIVATE FREE TEXT\nINSTRUCTIONS';s.symbol='UNBOUNDED USER SYMBOL PROSE';s.dataReference='PRIVATE REFERENCE PROSE';
  const r=failure(s,'snapshot-identity');assert.equal(r.snapshotId,null);assert.equal(r.symbol,null);assert.equal(r.dataReference,null);
  assert.doesNotMatch(JSON.stringify(r),/PRIVATE FREE|INSTRUCTIONS|UNBOUNDED USER|PRIVATE REFERENCE/);
});

test('aligned session gaps remain valid, and returned context is deeply frozen without aliases',()=>{
  const s=snapshot();s.series['15m'].candles.splice(5,1);const r=Evidence.extract(s,'15m');
  assert.equal(r.available,true);assert.equal(r.frames['15m'].closedBars,59);
  const before=JSON.stringify(r);s.series['15m'].candles.at(-1).close=1;s.id='caller-rewritten';
  assert.equal(JSON.stringify(r),before);
  assert.ok(Object.isFrozen(r));assert.ok(Object.isFrozen(r.frames));assert.ok(Object.isFrozen(r.frames['15m']));assert.ok(Object.isFrozen(r.facts[0].refs));assert.ok(Object.isFrozen(r.unknowns));
  assert.throws(()=>r.facts.push({id:'rewrite'}),TypeError);
});

const INTRADAY=['4h','1h','15m','5m'];
function swings(tf,{direction=1,count=60,end=CUTOFF}={}){
  const result=candles(tf,0,count,end);
  // Five-bar cycles create strict, unambiguous high and low pivots.
  const wave=[0,4,2,-4,-2];
  for(let i=0;i<count;i++){
    const center=200+direction*Math.floor(i/5)*2+wave[i%5];
    Object.assign(result[i],{open:center,close:center,high:center+.5,low:center-.5});
  }
  return result;
}
function intraday(){
  const s=snapshot();s.profile='intraday-v1';s.series={};
  INTRADAY.forEach((tf,i)=>s.series[tf]={status:'ready',source:'Deriv',capturedAt:CUTOFF+1,candles:swings(tf,{direction:i<2?1:-1})});
  return s;
}

test('intraday v2 has a fixed four-frame hierarchy independent of the selected chart horizon',()=>{
  const s=intraday();
  for(const tf of ['1m','5m','15m','1h','4h']){
    const r=Evidence.extract(s,tf);
    assert.equal(r.version,2);assert.equal(r.profile,'intraday-v1');assert.equal(r.available,true);
    assert.equal(r.timeframe,tf);assert.equal(r.higherTimeframe,null);assert.equal(r.asOf,CUTOFF);
    assert.deepEqual(r.requiredTimeframes,INTRADAY);assert.deepEqual(Object.keys(r.frames),INTRADAY);
    assert.equal(r.facts.length,4);assert.equal(r.frames['4h'].structure.trend,'up');
    assert.equal(r.frames['1h'].structure.trend,'up');assert.equal(r.frames['15m'].structure.trend,'down');
    assert.equal(r.frames['5m'].structure.trend,'down');
    assert.ok(Object.isFrozen(r.requiredTimeframes));assert.ok(Object.isFrozen(r.frames['4h'].structure.swingHighs[0]));
  }
  const legacy=Evidence.extract(snapshot(),'15m');assert.equal(legacy.version,1);
  assert.equal(legacy.profile,undefined);assert.equal(legacy.requiredTimeframes,undefined);assert.equal(legacy.frames['15m'].structure,undefined);
});

test('strict pivots require two completed bars to each side and report when they first became knowable',()=>{
  const s=intraday(),r=Evidence.extract(s,'15m');
  for(const tf of INTRADAY){
    const structure=r.frames[tf].structure,bars=s.series[tf].candles,seconds=SECONDS[tf];
    assert.equal(structure.method,'confirmed-swings-2x2-v1');assert.equal(structure.confirmationBars,2);
    assert.equal(structure.maximumLookbackBars,120);assert.equal(structure.lookbackBars,60);
    assert.equal(structure.from,bars[0].time);assert.equal(structure.through,bars.at(-1).time+seconds);
    for(const [key,priceKey]of [['swingHighs','high'],['swingLows','low']]){
      assert.equal(structure[key].length,2);
      for(const p of structure[key]){
        const i=bars.findIndex(b=>b.time===p.time);
        assert.ok(i>=2&&i<=bars.length-3);assert.equal(p.price,bars[i][priceKey]);
        assert.equal(p.confirmedAt,bars[i+2].time+seconds);assert.ok(p.confirmedAt<=r.asOf);
        for(const j of [i-2,i-1,i+1,i+2])assert.ok(priceKey==='high'?p.price>bars[j].high:p.price<bars[j].low);
      }
    }
    assert.equal(structure.lastCloseVsHigh,'below');assert.equal(structure.lastCloseVsLow,'above');
  }
});

test('forming and future candles cannot confirm the latest swing or alter the pinned structure',()=>{
  const s=intraday();
  for(const tf of INTRADAY){
    const row=s.series[tf],last=row.candles.at(-1);
    Object.assign(last,{open:1000,close:1000,high:1001,low:999});
  }
  const before=Evidence.extract(s,'15m');
  for(const tf of INTRADAY){
    const row=s.series[tf],seconds=SECONDS[tf],last=row.candles.at(-1);
    assert.ok(!before.frames[tf].structure.swingHighs.some(p=>p.time===last.time));
    for(let i=1;i<=3;i++)row.candles.push({time:last.time+i*seconds,open:200,close:200,high:201,low:199});
  }
  assert.deepEqual(Evidence.extract(s,'15m'),before);
  const now=Date.now;try{Date.now=()=>CUTOFF*1000+86400000;assert.deepEqual(Evidence.extract(s,'15m'),before);}finally{Date.now=now;}
});

test('pivot on the third-last bar is confirmed exactly at cutoff while the second-last remains unconfirmed',()=>{
  const s=intraday();
  for(const tf of INTRADAY){
    const row=s.series[tf],bars=row.candles;
    for(let i=bars.length-5;i<bars.length;i++)Object.assign(bars[i],{open:200,close:200,high:201,low:199});
    bars.at(-3).high=500;
  }
  const r=Evidence.extract(s,'15m');
  for(const tf of INTRADAY){
    const bars=s.series[tf].candles,p=r.frames[tf].structure.swingHighs.at(-1);
    assert.equal(p.time,bars.at(-3).time);assert.equal(p.price,500);
    assert.equal(p.confirmedAt,bars.at(-1).time+SECONDS[tf]);
    bars.at(-2).high=600;
  }
  const later=Evidence.extract(s,'15m');
  for(const tf of INTRADAY)assert.ok(!later.frames[tf].structure.swingHighs.some(p=>p.price===600||p.price===500));
});

test('bounded swing extraction excludes old extrema and tied highs or lows are not pivots',()=>{
  const s=intraday();
  for(const tf of INTRADAY){
    const row=s.series[tf];row.candles=swings(tf,{count:180});
    row.candles[5].high=9999;row.candles[8].low=.001;
  }
  const r=Evidence.extract(s,'15m');
  for(const tf of INTRADAY){
    const st=r.frames[tf].structure,bars=s.series[tf].candles;
    assert.equal(st.lookbackBars,120);assert.equal(st.from,bars[60].time);
    assert.ok(st.swingHighs.every(p=>p.time>=bars[62].time&&p.price!==9999));
    assert.ok(st.swingLows.every(p=>p.time>=bars[62].time&&p.price!==.001));
    for(const bar of bars)Object.assign(bar,{open:200,high:201,low:199,close:200});
  }
  const flat=Evidence.extract(s,'15m');
  for(const tf of INTRADAY){
    const st=flat.frames[tf].structure;
    assert.deepEqual(st.swingHighs,[]);assert.deepEqual(st.swingLows,[]);assert.equal(st.trend,'undetermined');
    assert.equal(st.lastCloseVsHigh,'unknown');assert.equal(st.lastCloseVsLow,'unknown');
  }
});

test('disagreeing high/low sequences are mixed; a displacement alone does not establish swing trend',()=>{
  const s=intraday();
  for(const tf of INTRADAY){
    const bars=s.series[tf].candles;
    for(let i=0;i<bars.length;i++){
      const cycle=Math.floor(i/5),phase=i%5;
      Object.assign(bars[i],{open:200,close:200,high:phase===1?210+cycle:201,low:phase===3?190-cycle:199});
    }
  }
  const r=Evidence.extract(s,'15m');
  for(const tf of INTRADAY)assert.equal(r.frames[tf].structure.trend,'mixed');
  for(const tf of INTRADAY)s.series[tf].candles=candles(tf,1);
  const linear=Evidence.extract(s,'15m');
  for(const tf of INTRADAY){assert.ok(linear.frames[tf].closeDisplacement20>0);assert.equal(linear.frames[tf].structure.trend,'undetermined');}
});

test('each unavailable, stale, malformed or relabelled required frame withholds the full review and preserves valid peers',()=>{
  for(const tf of INTRADAY){
    for(const [code,change]of [
      ['history-unavailable',s=>{delete s.series[tf];}],
      ['history-stale',s=>{s.series[tf].candles=swings(tf,{end:CUTOFF-SECONDS[tf]*4});}],
      ['history-integrity',s=>{s.series[tf].candles[10].close=Infinity;}],
      ['interval-integrity',s=>{s.series[tf].candles=swings(tf);s.series[tf].candles.forEach((b,i,a)=>{if(i===0)return;b.time=a[0].time+i*SECONDS[tf]*2;});}]
    ]){
      const s=intraday();change(s);const r=Evidence.extract(s,'15m');
      assert.equal(r.available,false);assert.equal(r.frames[tf],undefined);
      assert.ok(r.unknowns.some(u=>u.timeframe===tf&&u.code===code),JSON.stringify(r.unknowns));
      assert.equal(Object.keys(r.frames).length,3);assert.equal(r.facts.length,3);
    }
  }
});

test('intraday source and unrelated fields cannot leak ARIA, account, journal, user, or upstream prose',()=>{
  const s=intraday(),baseline=Evidence.extract(s,'15m');
  for(const field of ['aria','account','analysis','hypothesis','lessonRef','quote','settings'])Object.defineProperty(s,field,{get(){throw Error('Unrelated '+field+' read');}});
  for(const row of Object.values(s.series)){
    row.error='PRIVATE_SOURCE_ERROR';row.structure={trend:'up',reason:'CACHED_ARIA_PROMISE'};
    for(const bar of row.candles)bar.prose='PRIVATE_CANDLE_NOTE';
  }
  assert.deepEqual(Evidence.extract(s,'15m'),baseline);
  s.series['4h'].source='UNTRUSTED_PROVIDER_PROSE';const r=Evidence.extract(s,'15m');
  assert.equal(r.available,false);assert.doesNotMatch(JSON.stringify(r),/PRIVATE_|CACHED_ARIA_PROMISE|UNTRUSTED_PROVIDER_PROSE/);
  assert.ok(r.unknowns.some(u=>u.timeframe==='4h'&&u.code==='history-source'));
});

test('unknown profile is explicit and cannot silently fall back to the legacy two-frame review',()=>{
  const s=intraday();s.profile='UNTRUSTED_PROFILE_PROSE';const r=Evidence.extract(s,'15m');
  assert.equal(r.available,false);assert.ok(r.unknowns.some(u=>u.code==='unsupported-profile'));
  assert.equal(Object.keys(r.frames).length,0);assert.doesNotMatch(JSON.stringify(r),/UNTRUSTED_PROFILE_PROSE/);
});
