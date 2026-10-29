const {test}=require('node:test');
const assert=require('node:assert/strict');
const Market=require('../static/oracle-market.js');
const Oracle=require('../static/oracle-review.js');
const asOf=1800000000.5;
function bars(tf,count=260){const seconds=Market.SECONDS[tf],end=Math.floor(asOf/seconds)*seconds;
  return Array.from({length:count},(_,i)=>({time:end-(count-i)*seconds,open:100+i*.1,high:101+i*.1,low:99+i*.1,close:100.5+i*.1}));}
function dependencies(overrides={}){return{getContext:(symbol='A')=>({symbol,label:symbol,provider:'fixture',ticker:symbol}),
  loadRow:async(_,tf)=>bars(tf),captureExecution:()=>({quote:null,spec:null,account:{openRisk:0}}),captureAria:()=>{throw Error('ARIA must not be read during capture');},
  lessonRef:()=>({key:'lesson',completedCases:1}),now:()=>asOf*1000,id:()=> 'snapshot-1',...overrides};}
test('snapshot capture retrieves only the selected and mapped higher interval, without reading ARIA',async()=>{
  const calls=[];const service=Market.createService(dependencies({loadRow:async(ctx,tf)=>{calls.push([ctx.symbol,tf]);return bars(tf);}}));
  const h={symbol:'A',timeframe:'4h'},s=await service.captureSnapshot(h);
  assert.deepEqual(calls,[['A','4h'],['A','1d']]);assert.equal(s.asOf,asOf);assert.equal(s.aria,undefined);
  assert.match(s.dataReference,/fnv1a32-/);assert.equal(s.lessonRef.completedCases,1);
  assert.ok(Object.isFrozen(s));assert.ok(Object.isFrozen(s.series['4h'].candles[0]));
});
test('feed errors and wrong intervals remain explicit evidence failures, never substituted chart state',async()=>{
  const service=Market.createService(dependencies({loadRow:async(_,tf)=>{if(tf==='1h')throw Error('Offline');return bars('1m');}}));
  const s=await service.captureSnapshot({symbol:'A',timeframe:'15m'});
  assert.equal(s.series['15m'].status,'unavailable');assert.match(s.series['15m'].error,/interval/);
  assert.equal(s.series['1h'].status,'unavailable');assert.match(s.series['1h'].error,/Offline/);
  assert.deepEqual(s.series['1h'].candles,[]);
});
test('capture pins original instrument despite a workspace switch, cancellation prevents a partial result',async()=>{
  let active='A',release;const abort=new AbortController();
  const service=Market.createService(dependencies({getContext:symbol=>({symbol:symbol||active,provider:'fixture'}),loadRow:()=>new Promise(r=>release=r)}));
  const pending=service.captureSnapshot({symbol:'A',timeframe:'15m'},{signal:abort.signal});active='B';abort.abort();release(bars('15m'));
  await assert.rejects(pending,/cancelled/);
});
test('delayed comparison explains shared prices and method differences without modifying first review',()=>{
  const review=Market.freeze({assessment:'Insufficient information',unknowns:[{essential:true,title:'Costs unknown',fact:'No cost source'}]});
  const h={symbol:'A',timeframe:'15m',action:'short',method:'range-reversal'},s={id:'snap',symbol:'A',label:'Asset A'};
  const before=JSON.stringify(review);const a={available:true,snapshotId:'snap',symbol:'A',timeframe:'15m',direction:'long',verdict:'QUALIFIED',closedAt:asOf,lastClose:100};
  const c=Market.compare(review,h,s,a);assert.match(c.interpretationsDiffer.join(' '),/range|reversal|momentum/);
  assert.match(c.notes.join(' '),/shared evidence/);assert.equal(JSON.stringify(review),before);
  assert.equal(Market.compare(review,h,s,{...a,snapshotId:'other'}).factsAgreed.length,0);
});
test('first-pass review is invariant to separately revealed or reversed ARIA comparison',async()=>{
  const s=await Market.createService(dependencies()).captureSnapshot({symbol:'A',timeframe:'15m'});
  const h={symbol:'A',timeframe:'15m',action:'wait',method:'continuation',observation:'A visible recent recovery.',reasoning:'Waiting for another closed candle.',thesisLevel:120,invalidation:{price:119,condition:'close-below',reason:'A close below this level would challenge recovery.'},wait:{price:125,condition:'A completed candle above this level.',reason:'Wait for a confirmed break rather than presume it.'}};
  const first=Oracle.review(h,s);
  for(const direction of ['long','short'])Market.compare(first,h,s,{available:true,snapshotId:s.id,symbol:'A',timeframe:'15m',direction,closedAt:asOf,lastClose:126});
  assert.deepEqual(Oracle.review(h,s),first);
});

test('intraday capture independently requests four horizons under one cutoff and preserves local journal metadata',async()=>{
  const calls=[];let clock=asOf*1000;
  const service=Market.createService(dependencies({now:()=>clock,loadRow:async(ctx,tf)=>{
    calls.push([ctx.symbol,tf]);clock+=1250;return bars(tf).map(b=>({...b,close:b.open}));
  }}));
  const s=await service.captureSnapshot({symbol:'A',timeframe:'1m'},{profile:'intraday-v1'});
  assert.deepEqual(calls,[['A','4h'],['A','1h'],['A','15m'],['A','5m']]);
  assert.deepEqual(Object.keys(s.series),['4h','1h','15m','5m']);
  assert.equal(s.profile,'intraday-v1');assert.equal(s.version,1);assert.equal(s.asOf,asOf);
  assert.equal(s.capturedAt,asOf+5);assert.equal(s.aria,undefined);
  assert.equal(s.lessonRef.completedCases,1);assert.equal(s.account.openRisk,0);
  for(const [i,tf]of Market.INTRADAY_TIMEFRAMES.entries()){
    assert.equal(s.series[tf].capturedAt,asOf+(i+1)*1.25);
    assert.equal(s.series[tf].candles[1].time-s.series[tf].candles[0].time,Market.SECONDS[tf]);
    assert.ok(Object.isFrozen(s.series[tf].candles));
  }
});

test('intraday missing and relabelled histories remain separate failures without fallback or losing valid rows',async()=>{
  const calls=[];
  const service=Market.createService(dependencies({loadRow:async(_,tf)=>{
    calls.push(tf);if(tf==='1h')throw Error('Unavailable source');
    return bars(tf==='5m'?'15m':tf);
  }}));
  const s=await service.captureSnapshot({symbol:'A',timeframe:'4h'},{profile:'intraday-v1'});
  assert.deepEqual(calls,['4h','1h','15m','5m']);
  assert.equal(s.series['4h'].status,'ready');assert.equal(s.series['15m'].status,'ready');
  assert.equal(s.series['1h'].status,'unavailable');assert.equal(s.series['5m'].status,'unavailable');
  assert.match(s.series['5m'].error,/requested 5m interval/);
});

test('intraday rejects unaligned gaps, allows session gaps, and never silently downgrades an unknown profile',async()=>{
  const good=bars('5m');good.splice(8,2);
  assert.equal(Market.intervalError(good,'5m',{requireObservedInterval:true}),'');
  const bad=bars('5m');for(let i=10;i<bad.length;i++)bad[i].time+=1;
  assert.match(Market.intervalError(bad,'5m',{requireObservedInterval:true}),/interval/);
  let called=false;
  const service=Market.createService(dependencies({loadRow:async()=>{called=true;return bars('5m');}}));
  await assert.rejects(service.captureSnapshot({symbol:'A',timeframe:'15m'},{profile:'UNTRUSTED_PROFILE'}),/supported Oracle evidence profile/);
  assert.equal(called,false);
});

test('intraday cancellation during a later history prevents publishing a partial capture',async()=>{
  const abort=new AbortController(),calls=[];
  const service=Market.createService(dependencies({loadRow:async(_,tf)=>{
    calls.push(tf);if(tf==='15m')abort.abort();return bars(tf);
  }}));
  await assert.rejects(service.captureSnapshot({symbol:'A',timeframe:'15m'},{signal:abort.signal,profile:'intraday-v1'}),/cancelled/);
  assert.deepEqual(calls,['4h','1h','15m']);
});
