/*
 * A small outcome-led benchmark specified separately from oracle-review.js.
 * These fictional scenarios test bounded rule behavior, not predictive merit.
 * The held-out cases are requirements-derived examples, not statistically
 * representative market samples. Arithmetic has objective answers; labels
 * about context only evaluate the disclosed structured method.
 */
const {test}=require('node:test');
const assert=require('node:assert/strict');
const heldout=require('./fixtures/oracle-heldout.json');
const Oracle=require('../static/oracle-review.js');
const AS_OF=1800000000;
const seconds={'1m':60,'5m':300,'15m':900,'1h':3600,'4h':14400,'1d':86400};
const clone=value=>JSON.parse(JSON.stringify(value));

// Multi-phase trajectories with bounded intrabar ranges. Neither future bars
// nor a profitable outcome is available to the reviewer at decision time.
function candles(tf,direction=1,count=240,end=AS_OF) {
  const step=seconds[tf],boundary=Math.floor(end/step)*step;
  const levels=Array.from({length:count},(_,i)=>100+direction*i*.075+.18*Math.sin(i/3.8)+.09*Math.sin(i/1.7));
  const offset=110-levels.at(-1);
  return levels.map((level,i)=>{
    const close=level+offset,open=(i?levels[i-1]:level-direction*.06)+offset;
    return {time:boundary-(count-i)*step,open,high:Math.max(open,close)+.12,low:Math.min(open,close)-.12,close};
  });
}
function input(c={id:'base',market:'rising',method:'continuation',direction:'long'}) {
  const isShort=c.direction==='short', direction=isShort?-1:1;
  const selected=candles('15m',direction),higher=candles('1h',c.market==='higher-falling'?-1:direction);
  if(c.market==='higher-falling') selected.at(-1).low=Math.min(...selected.slice(-21,-1).map(b=>b.low))-.02;
  if(c.market==='breakout') {selected.at(-1).close=Math.max(...selected.slice(-21,-1).map(b=>b.high))+.2;selected.at(-1).high=selected.at(-1).close+.12;}
  const recent=selected.slice(-12),ref=isShort?Math.max(...recent.map(b=>b.high)):Math.min(...recent.map(b=>b.low));
  const price=selected.at(-1).close,invalid=ref+direction*-.2,stop=invalid-direction*.15;
  const h={version:1,id:`hyp-${c.id}`,symbol:'CASEUSD',label:'Fictional case/USD',timeframe:'15m',method:c.method,action:c.direction,
    observation:`The last completed 15m candle closed at ${price}; the visible reference is ${ref.toFixed(4)}.`,
    reasoning:isShort?'I am testing whether the observed falling prices continue after this closed-bar confirmation.':'I am testing whether the observed recovery can continue after this closed-bar confirmation.',
    thesisLevel:ref,entryCondition:'closed-confirmation',targetBasis:'fixed-multiple',
    invalidation:{condition:isShort?'close-above':'close-below',price:invalid,reason:'A completed candle beyond the observed reference would challenge the continuation idea.'},
    plan:{entry:price,stop,target:price+direction*Math.abs(price-stop)*2.5,quantity:2,cost:.5,openRisk:0,realizedLoss:0,perIdeaLimit:50,combinedLimit:100,dailyLossLimit:150},
    wait:{condition:'A completed 15m candle closes above the revisit reference.',price:price+1,reason:'Review only after a completed candle closes beyond this reference; that would justify another look, not an automatic entry.'}};
  const s={version:1,id:`snapshot-${c.id}`,asOf:AS_OF,capturedAt:AS_OF,symbol:h.symbol,label:h.label,provider:'Fictional held-out fixture',
    series:{'15m':{status:'ready',candles:selected,source:'Fictional held-out fixture: selected interval',capturedAt:AS_OF},'1h':{status:'ready',candles:higher,source:'Fictional held-out fixture: higher interval',capturedAt:AS_OF}},
    quote:{bid:price-.01,ask:price+.01,time:AS_OF-1,source:'Fictional two-sided quote'},
    spec:{valuePerPriceUnit:1,quantityStep:1,minQuantity:1,maxQuantity:10000,currency:'USD',source:'Fictional classroom specification; not verified broker specifications'},
    account:{openRisk:0,realizedLoss:0,perIdeaLimit:50,combinedLimit:100,dailyLossLimit:150,source:'Fictional configured paper guidance'},
    unsupported:['news','macro events','order flow','hidden liquidity','validated edge']};
  switch(c.change) {
    case 'wait-without-execution-inputs': h.plan={};s.quote=null;s.spec=null;break;
    case 'oversized': h.plan.quantity=100;break;
    case 'costs-over-budget': h.plan.perIdeaLimit=50;h.plan.cost=51;break;
    case 'stop-on-profit-side': h.plan.stop=price+direction;break;
    case 'stop-before-invalidation':h.plan.stop=(price+invalid)/2;break;
    case 'invalidation-wrong-side':h.invalidation.condition=isShort?'close-below':'close-above';h.invalidation.price=price+direction;break;
    case 'target-on-loss-side':h.plan.target=price-direction;break;
    case 'missing-invalidation-condition':h.invalidation.reason='';h.invalidation.condition='';break;
    case 'selected-history-short':s.series['15m'].candles=selected.slice(-8);break;
    case 'missing-higher-history':s.series['1h']={status:'unavailable',candles:[],source:'Fictional fixture',capturedAt:AS_OF,error:'No higher history'};break;
    case 'stale-selected-history':s.series['15m'].candles=selected.map(b=>({...b,time:b.time-86400}));break;
    case 'forming-only-history':s.series['15m'].candles=selected.map((b,i)=>({...b,time:AS_OF+i*seconds['15m']}));break;
    case 'incorrect-interval-history':s.series['15m'].candles=candles('1m');break;
    case 'unknown-costs':h.plan.cost=null;break;
    case 'missing-spec':s.spec=null;break;
    case 'stale-quote':s.quote.time=AS_OF-3600;break;
    case 'missing-source':s.series['15m'].source='';break;
    case 'raises-configured-cap':h.plan.quantity=100;h.plan.perIdeaLimit=10000;break;
    case 'hides-account-exposure':s.account.openRisk=99;h.plan.openRisk=0;break;
    case 'hides-realized-loss':s.account.realizedLoss=150;h.plan.realizedLoss=0;break;
    case 'confirmed-entry-outside-evidence':h.plan.entry=50;h.invalidation.price=49;h.plan.stop=48;h.plan.target=55;break;
    case 'unsupported-visible-target':h.targetBasis='visible-structure';h.plan.target=1000;break;
    case 'pending-breakout':h.entryCondition='conditional';break;
    case 'symbol-mismatch':s.symbol='ANOTHERUSD';break;
  }
  return {h,s};
}
const labels={supported:'Supported on available evidence',material:'Material concern',insufficient:'Insufficient information'};

test('held-out outcomes cover coherent, defective, contextual, and incomplete ideas',async t=>{
  assert.ok(heldout.cases.length>=20);
  for(const c of heldout.cases) await t.test(`${c.id}: ${c.purpose}`,()=>{
    const {h,s}=input(c),result=Oracle.review(h,s);
    assert.equal(result.assessment,labels[c.expected],`${c.id}: ${JSON.stringify(result)}`);
    if(c.expected==='material') assert.ok(result.constraints.length+result.concerns.length>0);
    if(c.expected==='insufficient') assert.ok(result.unknowns.length>0,'Withholding needs an explicit unknown');
    assert.equal(result.snapshotId,s.id);assert.equal(result.hypothesisId,h.id);
    for(const group of ['constraints','concerns','unknowns']) for(const finding of result[group]) {
      assert.ok(finding.fact?.trim(),`${group} lacks an observed fact: ${JSON.stringify(finding)}`);
      assert.ok(finding.relevance?.trim(),`${group} lacks relevance: ${JSON.stringify(finding)}`);
      assert.ok(finding.resolution?.trim(),`${group} lacks a resolution: ${JSON.stringify(finding)}`);
    }
    for(const field of ['confidence','winProbability','probability','score']) assert.equal(result[field],undefined);
    assert.ok(result.whatChanges.length>0,'Every review needs observable ways its assessment could change');
  });
});

test('first pass is invariant to hidden, displayed, or reversed ARIA endorsement',()=>{
  for(const c of heldout.cases) {
    const {h,s}=input(c),baseline=Oracle.review(h,s);
    for(const aria of [{verdict:'BUY',score:9,prose:'A highly supported long'},{verdict:'SELL',score:0,prose:'Strongly oppose long'},null]) {
      assert.deepEqual(Oracle.review({...clone(h),aria}, {...clone(s),aria}),baseline,c.id);
    }
  }
});

test('review is reproducible and leaves student input and evidence untouched',()=>{
  for(const c of heldout.cases) {
    const {h,s}=input(c),before=JSON.stringify({h,s}),a=Oracle.review(h,s),b=Oracle.review(clone(h),clone(s));
    assert.deepEqual(a,b,c.id);assert.equal(JSON.stringify({h,s}),before,c.id);
  }
});

test('future/forming extreme price changes cannot rewrite the completed-bar first assessment',()=>{
  const {h,s}=input(),a=Oracle.review(h,s);
  const future={time:AS_OF,open:110,high:500,low:1,close:1};
  const next=clone(s);next.series['15m'].candles.push(future,{...future,time:AS_OF+900});
  const b=Oracle.review(h,next);
  assert.equal(b.assessment,a.assessment);
  assert.deepEqual(b.constraints,a.constraints);assert.deepEqual(b.concerns,a.concerns);
  assert.equal(JSON.stringify(a).includes('500'),false);
});


test('objective cost-inclusive USD arithmetic is correct in both directions',()=>{
  for(const action of ['long','short']) {
    const {h,s}=input({id:'arithmetic-'+action,market:action==='long'?'rising':'falling',method:'continuation',direction:action});
    const sign=action==='long'?1:-1;
    h.invalidation.price=110-sign*2;
    h.plan={...h.plan,entry:110,stop:110-sign*3,target:110+sign*6,quantity:4,cost:3,openRisk:7,realizedLoss:11};
    s.spec.valuePerPriceUnit=2;
    s.account.openRisk=7;s.account.realizedLoss=11;
    const r=Oracle.review(h,s).metrics.risk;
    assert.equal(r.grossLoss,24);assert.equal(r.grossReward,48);
    assert.equal(r.plannedLoss,27);assert.equal(r.netReward,45);
    assert.equal(r.grossRewardRisk,2);assert.equal(r.netRewardRisk,45/27);
    assert.equal(r.combinedRisk,34);assert.equal(r.dailyAtRisk,45);
  }
});

test('material contradictions remain distinct from unknown evidence and cannot be averaged away',()=>{
  const {h,s}=input();h.plan.stop=h.plan.entry+1;h.plan.cost=null;s.quote=null;
  const r=Oracle.review(h,s);
  assert.equal(r.assessment,'Material concern');assert.ok(r.constraints.length>0);
  assert.ok(r.unknowns.some(f=>f.essential));
  assert.ok(r.constraints.every(f=>f.material));
});

test('result evidence and nested explanations are immutable after returning to a caller',()=>{
  const {h,s}=input(),r=Oracle.review(h,s),before=JSON.stringify(r);
  h.invalidation.price=100000;s.series['15m'].candles.at(-1).close=100000;
  assert.equal(JSON.stringify(r),before);
  assert.ok(Object.isFrozen(r));assert.ok(Object.isFrozen(r.metrics));
  assert.ok(Object.isFrozen(r.facts));assert.ok(Object.isFrozen(r.facts[0]));
  assert.throws(()=>r.facts.push({fact:'retroactive rewrite'}),TypeError);
});

// Export for the separate browser/integration harness if useful. No account,
// order-submission, fetch, or broker bridge is involved in this test module.
module.exports={input,candles,AS_OF};


test('reassessment change descriptions identify interior OHLC corrections and changed risk evidence',()=>{
  const {s}=input(),Workspace=require('../static/oracle-workspace.js');
  const interior=clone(s);interior.series['15m'].candles.at(-10).high+=2;
  const corrected=Workspace.snapshotChanges(s,interior).join(' ');
  assert.match(corrected,/15m/);assert.match(corrected,/OHLC|revision|high/i);
  assert.doesNotMatch(corrected,/No supplied OHLC/);
  const exposure=clone(s);exposure.account.openRisk=42;
  const riskChanges=Workspace.snapshotChanges(s,exposure).join(' ');
  assert.match(riskChanges,/openRisk/);assert.match(riskChanges,/42/);
  const cutoff=clone(s);cutoff.asOf+=1;
  assert.match(Workspace.snapshotChanges(s,cutoff).join(' '),/later capture time alone is not new confirmation/i);
});

const Workspace=require('../static/oracle-workspace.js');
const Market=require('../static/oracle-market.js');

test('local learning history preserves the first evidence and review through refresh, decision, reload and export',()=>{
  const {h,s}=input(),review=Oracle.review(h,s);
  const comparison={factsAgreed:['Shared completed price evidence'],interpretationsDiffer:[],missing:[],notes:['Separate criteria; no probability claim']};
  const created=Workspace.createRecord({hypothesis:h,snapshot:s,review,aria:{snapshotId:s.id,direction:'long'},comparison,lessonRef:{lessonId:'explain-idea',caseId:'level-retest'}},'record-1');
  const original=clone(created);
  h.reasoning='Later rewritten claim';s.series['15m'].candles.at(-1).high=9999;comparison.factsAgreed.push('Later claim');
  assert.deepEqual(created,original,'createRecord must own its saved evidence rather than alias callers');
  const later=clone(original.snapshot);later.id='snapshot-later';later.asOf+=900;later.capturedAt+=900;
  const laterReview=Oracle.review(original.hypothesis,later);
  const reassessed=Workspace.appendReassessment(created,{hypothesis:original.hypothesis,snapshot:later,review:laterReview,aria:null,comparison:null,changes:['New decision cutoff; the old review stays unchanged.']});
  assert.deepEqual(created,original,'Appending a later review cannot modify the first record');
  assert.deepEqual(reassessed.snapshot,original.snapshot);assert.deepEqual(reassessed.review,original.review);
  assert.equal(reassessed.reassessments.length,1);assert.equal(reassessed.reassessments[0].snapshot.id,'snapshot-later');
  later.id='caller-mutated';assert.equal(reassessed.reassessments[0].snapshot.id,'snapshot-later');
  const decided=Workspace.decideRecord(reassessed,{action:'retain',reason:'I retained this idea because the bounded evidence is unchanged, while the execution unknown remains.',reviewSnapshotId:'snapshot-later',at:'2026-10-19T14:00:00.000Z'});
  assert.equal(reassessed.decision,null);assert.equal(decided.decision.reviewSnapshotId,'snapshot-later');
  assert.throws(()=>Workspace.decideRecord(decided,{action:'withdraw',reason:'Rewrite the earlier rationale after later prices.'}));
  const state={version:1,draft:null,records:[decided],selectedId:'record-1',screen:'review',updatedAt:'2026-10-19T14:00:00.000Z'};
  const store=new Map(),storage={getItem:key=>store.get(key),setItem:(key,value)=>store.set(key,value)};
  assert.equal(Workspace.writeState(storage,state),'');
  const loaded=Workspace.readState(storage);assert.equal(loaded.warning,'');assert.deepEqual(loaded.state.records,state.records);
  const exported=Workspace.exportRecord(loaded.state);assert.deepEqual(exported.records,state.records);
  assert.match(exported.persistence,/browser only/i);assert.match(exported.reviewMethod,/rules.*not an AI/i);
  exported.records[0].hypothesis.reasoning='Edited export';assert.notEqual(loaded.state.records[0].hypothesis.reasoning,'Edited export');
});

test('mismatched evidence is not saved as the student hypothesis review, and storage failure remains visible',()=>{
  const {h,s}=input(),review=Oracle.review(h,s);
  assert.throws(()=>Workspace.createRecord({hypothesis:h,snapshot:{...s,symbol:'OTHER'},review}));
  assert.throws(()=>Workspace.createRecord({hypothesis:h,snapshot:s,review:{...review,snapshotId:'unrelated'}}));
  const record=Workspace.createRecord({hypothesis:h,snapshot:s,review},'record-1');
  assert.throws(()=>Workspace.appendReassessment(record,{hypothesis:h,snapshot:s,review:{...review,snapshotId:'unrelated'}}));
  let writes=0;const inaccessible={getItem(){throw Error('Blocked');},setItem(){writes++;throw Error('Quota');}};
  assert.match(Workspace.readState(inaccessible).warning,/untouched|export/i);assert.equal(writes,0);
  assert.match(Workspace.writeState(inaccessible,{version:1,records:[record]}),/could not save/i);
  const corrupt=Workspace.readState({getItem:()=>'{malformed'});assert.match(corrupt.warning,/untouched/i);
});

test('evidence capture freezes separate interval histories before the ARIA comparison is requested',async()=>{
  const {h,s}=input(),requests=[];let ariaCalls=0,clock=AS_OF*1000;
  const raw=clone(s.series);
  const service=Market.createService({now:()=>clock,id:()=>s.id,getContext:symbol=>({symbol:symbol||h.symbol,label:h.label,provider:s.provider}),
    loadRow:async(context,tf)=>{requests.push([context.symbol,tf]);clock+=1000;return raw[tf].candles;},
    captureExecution:()=>({quote:s.quote,spec:s.spec,account:s.account}),captureAria:()=>{ariaCalls++;return{available:false,reason:'Explicit test comparison'};}});
  const captured=await service.captureSnapshot(h);
  assert.deepEqual(requests,[[h.symbol,'15m'],[h.symbol,'1h']]);assert.equal(ariaCalls,0);
  assert.equal(captured.asOf,AS_OF);assert.equal(captured.capturedAt,AS_OF+2);
  assert.ok(captured.dataReference);assert.ok(Object.isFrozen(captured.series['15m'].candles[0]));
  const saved=clone(captured);raw['15m'].candles.at(-1).close=1;assert.deepEqual(captured,saved);
  const first=Oracle.review(h,captured);service.captureAria(captured,h);assert.equal(ariaCalls,1);
  assert.deepEqual(Oracle.review(h,captured),first,'A later comparison request cannot alter the first pass');
});

test('capture cancellation and comparison context mismatch cannot masquerade as independent agreement',async()=>{
  const {h,s}=input();let release;
  const service=Market.createService({now:()=>AS_OF*1000,id:()=>s.id,getContext:symbol=>({symbol:symbol||h.symbol,label:h.label,provider:s.provider}),
    loadRow:()=>new Promise(resolve=>release=resolve),captureExecution:()=>({quote:s.quote,spec:s.spec,account:s.account}),captureAria:()=>null});
  const cancel=new AbortController(),pending=service.captureSnapshot(h,{signal:cancel.signal});
  cancel.abort();release(s.series['15m'].candles);await assert.rejects(pending,/cancelled/i);
  const review=Oracle.review(h,s);
  for(const mismatch of [{snapshotId:'old'},{symbol:'OTHER'},{timeframe:'1h'}]) {
    const comparison=Market.compare(review,h,s,{available:true,snapshotId:s.id,symbol:s.symbol,timeframe:h.timeframe,closedAt:AS_OF,lastClose:110,direction:'long',...mismatch});
    assert.equal(comparison.factsAgreed.length,0);assert.ok(comparison.missing.length>0);
    assert.match(comparison.missing.join(' '),/different|cannot/i);
  }
});
