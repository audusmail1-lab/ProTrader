const {test}=require('node:test');
const assert=require('node:assert/strict');
const Oracle=require('../static/oracle-review.js');
const now=1800000000,clone=x=>JSON.parse(JSON.stringify(x));
function bars(tf,direction=1,count=40) {
  const seconds=Oracle.intervals[tf],end=Math.floor(now/seconds)*seconds;
  return Array.from({length:count},(_,i)=>{
    const close=104-direction*(count-i-1)*.1;
    return {time:end-(count-i)*seconds,open:close-direction*.05,high:close+.2,low:close-.2,close};
  });
}
function input() {
  const h={version:1,id:'h1',symbol:'CASE',label:'Fictional unit fixture',timeframe:'15m',method:'continuation',action:'long',
    observation:'The latest completed 15m candle closed at 104.',reasoning:'I am testing continuation after the observed upward close displacement.',
    thesisLevel:102,entryCondition:'closed-confirmation',targetBasis:'fixed-multiple',
    invalidation:{condition:'close-below',price:102,reason:'A completed close below the visible reference challenges this thesis.'},
    plan:{entry:104,stop:101.5,target:109,quantity:2,cost:1,openRisk:1,realizedLoss:2,perIdeaLimit:10,combinedLimit:25,dailyLossLimit:40},
    wait:{condition:'close-above',price:105,reason:'Wait for the declared reference to be crossed on a completed candle.'}};
  const s={version:1,id:'s1',asOf:now,capturedAt:now,symbol:'CASE',label:h.label,provider:'Fictional unit fixture',
    series:Object.fromEntries(['15m','1h'].map(tf=>[tf,{status:'ready',candles:bars(tf),source:'Fictional test source',capturedAt:now}])),
    quote:{bid:103.99,ask:104.01,time:now-1,source:'Fictional sourced quote'},
    spec:{valuePerPriceUnit:1,quantityStep:.5,minQuantity:.5,maxQuantity:20,currency:'USD',source:'Fictional paper model, not verified broker terms'},
    account:{openRisk:1,realizedLoss:2,perIdeaLimit:10,combinedLimit:25,dailyLossLimit:40,source:'Fictional paper guidance'}};
  return {h,s};
}
test('objective paper arithmetic includes total costs and retained exposure in dollar budgets',()=>{
  const {h,s}=input(),r=Oracle.review(h,s),m=r.metrics.risk;
  assert.equal(r.assessment,'Supported on available evidence');
  assert.equal(m.distance,2.5);assert.equal(m.rewardDistance,5);
  assert.equal(m.grossLoss,5);assert.equal(m.grossReward,10);
  assert.equal(m.plannedLoss,6);assert.equal(m.netReward,9);
  assert.equal(m.grossRewardRisk,2);assert.equal(m.netRewardRisk,1.5);
  assert.equal(m.combinedRisk,7);assert.equal(m.dailyAtRisk,9);
  assert.equal(r.unknowns.find(f=>f.id==='unsupported-context').essential,false);
  assert.equal(r.unknowns.find(f=>f.id==='execution-scope').essential,false);
});
test('risk limits are exact arithmetic constraints, without a universal reward/risk target',()=>{
  const {h,s}=input();h.plan.quantity=3.6;s.spec.quantityStep=.1;
  // $9 price loss + $1 total cost = exactly $10 configured guidance.
  let r=Oracle.review(h,s);assert.equal(r.constraints.some(f=>f.id==='idea-budget'),false);
  h.plan.quantity=3.7;r=Oracle.review(h,s);
  assert.equal(r.assessment,'Material concern');assert.ok(r.constraints.some(f=>f.id==='idea-budget'));
  h.plan.quantity=1;h.plan.target=104.25;h.plan.cost=0;r=Oracle.review(h,s);
  assert.equal(r.assessment,'Supported on available evidence');
  assert.equal(r.metrics.risk.grossRewardRisk,.1);
});
test('configured caps/exposure cannot be erased by paper-plan assumptions',()=>{
  const {h,s}=input();h.plan.perIdeaLimit=10000;h.plan.combinedLimit=10000;h.plan.dailyLossLimit=10000;
  h.plan.openRisk=0;h.plan.realizedLoss=0;s.account.openRisk=24;s.account.realizedLoss=39;
  const r=Oracle.review(h,s);
  assert.deepEqual(r.metrics.riskAssumptions,{openRisk:24,realizedLoss:39,perIdeaLimit:10,combinedLimit:25,dailyLossLimit:40});
  assert.equal(r.metrics.risk.combinedRisk,30);assert.equal(r.metrics.risk.dailyAtRisk,69);
  assert.ok(r.constraints.some(f=>f.id==='combined-budget'));assert.ok(r.constraints.some(f=>f.id==='daily-budget'));
});
test('captured zero budgets remain exhausted despite larger student declarations',()=>{
  for(const [key,id] of [['perIdeaLimit','idea-budget'],['combinedLimit','combined-budget'],['dailyLossLimit','daily-budget']]) {
    const {h,s}=input();s.account[key]=0;h.plan[key]=10000;
    const r=Oracle.review(h,s);
    assert.equal(r.metrics.riskAssumptions[key],0,key);
    assert.equal(r.assessment,'Material concern',key);
    assert.ok(r.constraints.some(f=>f.id===id),key);
    assert.ok(r.concerns.some(f=>f.id==='limit-override-'+key),key);
  }
});
test('negative and nonfinite captured budgets cannot be replaced by positive student caps',()=>{
  for(const key of ['perIdeaLimit','combinedLimit','dailyLossLimit']) for(const value of [-1,NaN,Infinity,-Infinity]) {
    const {h,s}=input();s.account[key]=value;h.plan[key]=10000;
    const r=Oracle.review(h,s);
    assert.equal(r.assessment,'Insufficient information',`${key}: ${value}`);
    assert.equal(r.metrics.riskAssumptions[key],null);
    assert.equal(r.metrics.riskProvenance[key].capturedInvalid,true);
    assert.ok(r.unknowns.some(f=>f.id==='invalid-captured-'+key&&f.essential));
  }
});
test('invalid captured budget markers survive JSON capture and local persistence',()=>{
  for(const key of ['perIdeaLimit','combinedLimit','dailyLossLimit']) {
    const {h,s}=input();s.account[key]=Infinity;s.account.invalidLimits=[key];h.plan[key]=10000;
    const persisted=JSON.parse(JSON.stringify(s));
    assert.equal(persisted.account[key],null,'JSON loses the scalar but retains explicit invalid provenance');
    const r=Oracle.review(h,persisted);
    assert.equal(r.assessment,'Insufficient information');
    assert.equal(r.metrics.riskAssumptions[key],null);
    assert.equal(r.metrics.riskProvenance[key].capturedInvalid,true);
    assert.ok(r.unknowns.some(f=>f.id==='invalid-captured-'+key&&f.essential));
    assert.match(r.unknowns.find(f=>f.id==='invalid-captured-'+key).fact,/before serialization/);
    assert.deepEqual(Oracle.review(JSON.parse(JSON.stringify(h)),JSON.parse(JSON.stringify(persisted))),r);
  }
});
test('student zero budgets also mean exhausted, while explicit missing captured caps allow declared assumptions',()=>{
  for(const [key,id] of [['perIdeaLimit','idea-budget'],['combinedLimit','combined-budget'],['dailyLossLimit','daily-budget']]) {
    for(const captured of [null,100]) {
      const {h,s}=input();s.account[key]=captured;h.plan[key]=0;
      const r=Oracle.review(h,s);assert.equal(r.metrics.riskAssumptions[key],0);
      assert.equal(r.assessment,'Material concern');assert.ok(r.constraints.some(f=>f.id===id));
    }
    const {h,s}=input();s.account[key]=null;
    assert.equal(Oracle.review(h,s).assessment,'Supported on available evidence');
  }
});
test('missing values remain unknown, including null costs and a quote older than 30 seconds',()=>{
  for (const change of [
    ({h})=>h.plan.cost=null,({s})=>s.quote=null,({s})=>s.quote.time=now-31,
    ({s})=>s.spec.source='',({h,s})=>{h.plan.openRisk=null;s.account.openRisk=null;}
  ]) {const item=input();change(item);const r=Oracle.review(item.h,item.s);
    assert.equal(r.assessment,'Insufficient information');assert.ok(r.unknowns.some(f=>f.essential));}
  const {h,s}=input();h.plan.cost=0;assert.equal(Oracle.review(h,s).metrics.risk.cost,0);
});
test('malformed quote, quantity grid and negative exposure cannot pass arithmetic',()=>{
  const {h,s}=input();s.quote.ask=103;assert.ok(Oracle.review(h,s).unknowns.some(f=>f.id==='quote'));
  s.quote.ask=104.01;h.plan.quantity=2.2;assert.ok(Oracle.review(h,s).constraints.some(f=>f.id==='quantity'));
  h.plan.quantity=2;h.plan.openRisk=-20;assert.ok(Oracle.review(h,s).constraints.some(f=>f.id==='invalid-openRisk'));
});
test('closed-confirmation and pending breakout have different truthful statuses',()=>{
  const {h,s}=input();h.method='breakout';
  let r=Oracle.review(h,s);assert.equal(r.assessment,'Material concern');assert.ok(r.concerns.some(f=>f.id==='breakout-confirmation'&&f.material));
  h.entryCondition='conditional';r=Oracle.review(h,s);
  assert.equal(r.assessment,'Insufficient information');assert.ok(r.concerns.some(f=>f.id==='breakout-confirmation'&&f.essential));
  h.entryCondition='closed-confirmation';s.series['15m'].candles.at(-1).close=104.5;s.series['15m'].candles.at(-1).high=104.6;h.plan.entry=104.5;
  r=Oracle.review(h,s);assert.equal(r.assessment,'Supported on available evidence');assert.ok(r.facts.some(f=>f.id==='breakout-observed'));
});
test('invalidation, entry/target references and stop geometry are explained distinctly',()=>{
  const cases=[
    [({h})=>h.invalidation.price=102.5,'invalidation-thesis'],
    [({h})=>h.plan.stop=102.5,'stop-invalidation'],
    [({h})=>h.plan.entry=106,'entry-evidence'],
    [({h})=>{h.targetBasis='visible-structure';h.plan.target=109;},'target-structure']
  ];
  for(const [change,id] of cases) {const item=input();change(item);const r=Oracle.review(item.h,item.s);
    const f=[...r.constraints,...r.concerns].find(f=>f.id===id);assert.ok(f,id);assert.ok(f.fact&&f.relevance&&f.resolution);}
});
test('evidence requires attributable, integral intervals and captured final candles',()=>{
  const cases=[
    [({s})=>s.series['15m'].capturedAt=now-1,'capture-15m'],
    [({s})=>s.series['15m'].candles[5].time+=1,'integrity-15m'],
    [({s})=>s.series['15m'].source='','source-15m'],
    [({s})=>s.series['15m'].candles=s.series['15m'].candles.slice(-29),'insufficient-15m'],
    [({s})=>s.symbol='DIFFERENT','symbol']
  ];
  for(const [change,id] of cases) {const item=input();change(item);const r=Oracle.review(item.h,item.s);
    assert.equal(r.assessment,'Insufficient information');assert.ok(r.unknowns.some(f=>f.id===id),id);}
});
test('forming/future bars never enter structural facts or turn cached evidence final',()=>{
  const {h,s}=input(),before=Oracle.review(h,s),last=s.series['15m'].candles.at(-1);
  s.series['15m'].candles.push({...last,time:now,high:9999,low:1,close:1});
  const r=Oracle.review(h,s);assert.equal(r.assessment,before.assessment);
  assert.equal(r.metrics['15m'].lastClose,104);assert.equal(r.metrics['15m'].excludedBars,1);
  assert.equal(r.metrics['15m'].priorHigh,before.metrics['15m'].priorHigh);
  s.asOf=now+900;s.capturedAt=now+900;
  const later=Oracle.review(h,s);assert.ok(later.unknowns.some(f=>f.id==='capture-15m'));
});
test('timeframe mapping includes daily context for 4h and rejects unsupported horizon',()=>{
  const {h,s}=input();h.timeframe='4h';s.series={};
  for(const tf of ['4h','1d']) s.series[tf]={status:'ready',candles:bars(tf),source:'Fictional source',capturedAt:now};
  const r=Oracle.review(h,s);assert.equal(r.assessment,'Supported on available evidence');assert.ok(r.metrics['1d']);
  h.timeframe='2m';assert.ok(Oracle.review(h,s).unknowns.some(f=>f.id==='timeframe'));
});
test('review is immutable, reproducible, side-effect-free and blind to ARIA fields',()=>{
  const {h,s}=input(),original=clone({h,s}),r=Oracle.review(h,s),encoded=JSON.stringify(r);
  assert.deepEqual({h,s},original);assert.equal(Object.isFrozen(r),true);assert.equal(Object.isFrozen(r.metrics.risk),true);
  h.plan.quantity=10000;s.series['15m'].candles.at(-1).close=1;
  assert.equal(JSON.stringify(r),encoded);
  for(const aria of [undefined,{verdict:'BUY',score:9,prose:'Endorsed'},{verdict:'SELL',score:0,prose:'Rejected'}])
    assert.deepEqual(Oracle.review({...original.h,aria},{...original.s,aria}),r);
  assert.equal(typeof Oracle.submitOrder,'undefined');assert.equal(typeof Oracle.fetch,'undefined');
});
test('wait is supported without executable inputs and unsupported free text remains unassessed',()=>{
  const {h,s}=input();h.action='wait';h.plan={};s.spec=null;s.quote=null;
  const r=Oracle.review(h,s);assert.equal(r.assessment,'Supported on available evidence');
  assert.equal(r.unknowns.find(f=>f.id==='execution-scope').essential,false);
  h.method='other';assert.equal(Oracle.review(h,s).assessment,'Insufficient information');
});
