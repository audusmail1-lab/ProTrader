const {test}=require('node:test');
const assert=require('node:assert/strict');
const {analyze,createController,timeframes,intervals}=require('../static/mtf-analysis.js');
const now=1800000000;
function fixture(tf, direction=1, count=260, end=now) {
  const sec=intervals[tf], boundary=Math.floor(end/sec)*sec;
  return Array.from({length:count},(_,i)=>{
    const close=300+direction*i*.2;
    return {time:boundary-(count-i)*sec,open:close-direction*.1,high:close+.3,low:close-.3,close};
  });
}
const settle=()=>new Promise(resolve=>setImmediate(resolve));
test('independent timeframe fixtures produce independently different rows and actual indicator values', async()=>{
  let snapshot; const requested=[];
  const signs=[1,-1,1,-1,1];
  const c=createController({now:()=>now*1000,onChange:s=>snapshot=s,
    loadRow:async(ctx,tf)=>{requested.push(`${ctx.symbol}:${tf}`); return fixture(tf,signs[timeframes.indexOf(tf)]);}});
  await c.select({symbol:'A',provider:'fixture'});
  assert.deepEqual(requested,timeframes.map(tf=>`A:${tf}`));
  for (let i=0;i<timeframes.length;i++) {
    const r=snapshot.rows[timeframes[i]], expected=signs[i]>0?'bull':'bear';
    assert.equal(r.status,'ready'); assert.equal(r.directions[0],expected);
    assert.equal(r.directions[1],expected); assert.equal(r.directions[2],expected);
    assert.equal(r.directions[3],expected); assert.equal(r.values.rsi,signs[i]>0?100:0);
    assert.equal(r.closedAt,Math.floor(now/intervals[timeframes[i]])*intervals[timeframes[i]]);
  }
});
test('insufficient, malformed, unsupported and stale histories never carry directional arrows',()=>{
  for(const [candles,tf,status] of [
    [fixture('1m',1,40),'1m','insufficient'],
    [[], '1m','unavailable'], [fixture('1m'),'2m','unsupported'],
    [fixture('1m',1,260,now-10000),'1m','stale'],
    [fixture('1m').map((c,i)=>i===10?{...c,close:null}:c),'1m','unavailable'],
    [fixture('1m'),'5m','unavailable']
  ]) { const r=analyze(candles,tf,now); assert.equal(r.status,status); assert.equal(r.directions,undefined); }
});
test('forming and future bars cannot change closed-bar analysis; flat data is neutral',()=>{
  const base=fixture('1m'); const r=analyze(base,'1m',now);
  const future={time:Math.floor(now/60)*60,open:100,high:10000,low:1,close:1};
  const next=analyze([...base,future,{...future,time:future.time+60}],'1m',now);
  assert.deepEqual(next,r);
  const flat=fixture('1m',0);const n=analyze(flat,'1m',now);
  assert.deepEqual(n.directions,['neut','neut','neut','neut']);assert.equal(n.values.rsi,50);
});
test('a final closed candle with finer spacing cannot masquerade as this interval',()=>{
  const candles=fixture('5m');
  const final={...candles.at(-1),time:candles.at(-1).time+60,low:1,close:1};
  const result=analyze([...candles,final],'5m',now+120);
  assert.equal(result.status,'unavailable');assert.equal(result.directions,undefined);
});
test('coarser candles and unaligned gaps cannot be relabelled as a finer interval',()=>{
  for(const bars of [fixture('15m'),fixture('5m').map((b,i)=>({...b,time:b.time-(i<100?17:0)}))]){
    const row=analyze(bars,'5m',now);
    assert.equal(row.status,'unavailable');assert.equal(row.directions,undefined);
  }
});
test('aligned session gaps retain genuine native interval evidence',()=>{
  const bars=fixture('5m').map((b,i)=>({...b,time:b.time-(i<100?172800:0)}));
  assert.equal(analyze(bars,'5m',now).status,'ready');
});
test('a forming native-spaced bar cannot validate a coarse completed history',()=>{
  const bars=fixture('15m');
  const latest={...bars.at(-1),time:bars.at(-1).time+300};
  const row=analyze([...bars,latest],'5m',latest.time+299);
  assert.equal(row.status,'unavailable');assert.equal(row.directions,undefined);
});
test('invalid cutoffs and excessive evidence remain unavailable',()=>{
  for(const cutoff of [NaN,Infinity,0,-1])assert.equal(analyze(fixture('5m'),'5m',cutoff).status,'unavailable');
  assert.equal(analyze(fixture('5m',1,5001),'5m',now).status,'unavailable');
});
test('symbol and provider switches abort and discard old responses even if the adapter ignores abort',async()=>{
  let resolveA,snapshot,oldSignal;
  const c=createController({now:()=>now*1000,onChange:s=>snapshot=s,
    loadRow:(ctx,tf,signal)=>ctx.symbol==='A'?new Promise(r=>{resolveA=r;oldSignal=signal;}):Promise.resolve(fixture(tf,-1))});
  const a=c.select({symbol:'A',provider:'first'});
  await c.select({symbol:'B',provider:'first'});
  assert.equal(oldSignal.aborted,true); assert.equal(snapshot.context.symbol,'B');
  resolveA(fixture('1m',1));await a;assert.equal(snapshot.rows['1m'].directions[0],'bear');
  await c.select({symbol:'B',provider:'second'});assert.equal(snapshot.context.provider,'second');
});
test('cache bounds requests and never promotes a previously forming bar to closed',async()=>{
  let clock=now*1000, snapshot,requests=0;
  const c=createController({now:()=>clock,onChange:s=>snapshot=s,loadRow:async(_,tf)=>{
    requests++;const bars=fixture(tf);return [...bars,{...bars.at(-1),time:bars.at(-1).time+intervals[tf],high:9999,close:9999}];
  }});
  await c.select({symbol:'A',provider:'fixture'});const initial=snapshot.rows['1m'].closedAt;
  clock+=59000; await c.refresh();assert.equal(requests,5);
  assert.equal(snapshot.rows['1m'].closedAt,initial);
  clock+=2000;await c.refresh();assert.equal(requests,10);
});
test('failed refresh removes old arrows and retries are limited; stopping cancels pending responses',async()=>{
  let clock=now*1000,snapshot,fail=false,requests=0;
  const c=createController({now:()=>clock,onChange:s=>snapshot=s,loadRow:async(_,tf)=>{
    requests++;if(fail)throw Error('Disconnected');return fixture(tf);
  }});
  await c.select({symbol:'A',provider:'fixture'});fail=true;clock+=61000;await c.refresh();
  for(const r of Object.values(snapshot.rows)) {assert.equal(r.status,'unavailable');assert.equal(r.directions,undefined);}
  await c.refresh();assert.equal(requests,10);
  c.stop();await settle();assert.match(snapshot.rows['1m'].message,/Offline/);
});
test('malformed response cannot become valid through cache filtering without a new retrieval',async()=>{
  let snapshot, requests=0;
  const c=createController({now:()=>now*1000,onChange:s=>snapshot=s,loadRow:async(_,tf)=>{
    requests++;return [{...fixture(tf)[0],time:null},...fixture(tf)];
  }});
  await c.select({symbol:'A',provider:'fixture'});await c.refresh();
  assert.equal(requests,5);
  for(const row of Object.values(snapshot.rows)) {assert.equal(row.status,'unavailable');assert.equal(row.directions,undefined);}
});
test('earlier rows age out even while another timeframe request is pending',async()=>{
  let clock=now*1000,snapshot,release;
  const c=createController({now:()=>clock,onChange:s=>snapshot=s,loadRow:(_,tf)=>tf==='5m'?new Promise(r=>release=r):Promise.resolve(fixture(tf))});
  const pending=c.select({symbol:'A',provider:'fixture'});await settle();
  assert.equal(snapshot.rows['1m'].status,'ready');clock+=181000;await c.refresh();
  assert.equal(snapshot.rows['1m'].status,'stale');assert.equal(snapshot.rows['1m'].directions,undefined);
  c.stop();release(fixture('5m'));await pending;
});
