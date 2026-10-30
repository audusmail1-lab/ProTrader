/* Acceptance tests for calculated MTF interpretation. Synthetic candles exercise
 * the actual extractor; they do not establish prediction or trading performance. */
const {test}=require('node:test');
const assert=require('node:assert/strict');
const Evidence=require('../static/oracle-evidence.js');

const FRAMES=['4h','1h','15m','5m'];
const SECONDS={'4h':14400,'1h':3600,'15m':900,'5m':300};
const CUTOFF=Date.UTC(2026,9,29,12,37,30)/1000;
const clone=value=>JSON.parse(JSON.stringify(value));

function candles(tf,kind='up',{count=60,cutoff=CUTOFF}={}){
  const seconds=SECONDS[tf],end=Math.floor(cutoff/seconds)*seconds;
  const wave=[0,4,2,-4,-2],direction=kind==='down'?-1:1;
  return Array.from({length:count},(_,i)=>{
    const cycle=Math.floor(i/5),phase=i%5;
    const center=kind==='flat'||kind==='mixed'?200:kind==='linear'?200+i*.4:200+direction*cycle*2+wave[phase];
    return {time:end-(count-i)*seconds,open:center,close:center,
      high:kind==='mixed'?(phase===1?210+cycle:201):center+.5,
      low:kind==='mixed'?(phase===3?190-cycle:199):center-.5};
  });
}
function snapshot(kinds=['up','up','up','up']){
  return {version:1,profile:'intraday-v1',id:'interpretation-acceptance',symbol:'R_50',
    provider:'Deriv',asOf:CUTOFF,capturedAt:CUTOFF+2,dataReference:'fnv1a32-1234abcd',
    series:Object.fromEntries(FRAMES.map((tf,i)=>[tf,{status:'ready',source:'Deriv',
      capturedAt:CUTOFF+1,candles:candles(tf,kinds[i])}]))};
}
function read(s=snapshot(),selected='15m'){
  const evidence=Evidence.extract(s,selected),before=JSON.stringify(evidence);
  assert.equal(typeof Evidence.interpret,'function','OracleEvidence.interpret must be exported');
  const result=Evidence.interpret(evidence);
  assert.equal(JSON.stringify(evidence),before,'Interpretation cannot rewrite its independent evidence');
  return {evidence,result};
}
function row(result,tf){const matches=result.frames.filter(frame=>frame.timeframe===tf);assert.equal(matches.length,1,tf);return matches[0];}
function useful(value,label){assert.equal(typeof value,'string',label);assert.ok(value.trim().length>0,label);assert.doesNotMatch(value,/awaiting interpretation|waiting for (?:an? )?interpretation/i,label);}
function complete(result){
  assert.equal(result.version,1);assert.equal(result.source,'calculated-rules');
  assert.equal(result.profile,'intraday-v1');assert.equal(result.available,true);
  assert.deepEqual(result.frames.map(frame=>frame.timeframe),FRAMES);
  for(const key of ['governing','reading','support','concern','setupCondition','setupInvalidation','contextInvalidation'])useful(result[key],key);
  for(const frame of result.frames){
    assert.ok(['bullish','bearish','mixed','undetermined','unavailable'].includes(frame.bias));
    for(const key of ['verdict','reading','evidence','phase','changeCondition'])useful(frame[key],`${frame.timeframe} ${key}`);
  }
  assert.equal(result.score,undefined);assert.equal(result.mtfScore,undefined);
  assert.equal(result.confidence,undefined);assert.equal(result.probability,undefined);
}
function challenge(s,tf){
  const evidence=Evidence.extract(s,'15m'),structure=evidence.frames[tf].structure;
  assert.ok(['up','down'].includes(structure.trend));
  const last=s.series[tf].candles.at(-1);
  const close=structure.trend==='up'?structure.swingLows.at(-1).price-1:structure.swingHighs.at(-1).price+1;
  Object.assign(last,{open:close,close,high:close+.25,low:close-.25});
}

test('four confirmed upward or downward structures receive immediate, attributable readings',()=>{
  for(const [kind,bias] of [['up','bullish'],['down','bearish']]){
    const {evidence,result}=read(snapshot(FRAMES.map(()=>kind)));complete(result);
    assert.equal(evidence.available,true);assert.equal(result.relationship,'aligned');
    for(const tf of FRAMES){assert.equal(evidence.frames[tf].structure.trend,kind);assert.equal(row(result,tf).bias,bias);}
    assert.match(result.governing,/4h/i);assert.match(result.contextInvalidation,/4h/i);
    assert.match(result.setupInvalidation,/15m/i);
  }
});

test('opposing 4h and 1h context remains conflicting even when two lower frames agree with 4h',()=>{
  for(const kinds of [['up','down','up','up'],['down','up','down','down']]){
    const {result}=read(snapshot(kinds));complete(result);
    assert.equal(result.relationship,'conflicting');
    assert.notEqual(row(result,'4h').bias,row(result,'1h').bias);
    assert.equal(row(result,'15m').bias,row(result,'4h').bias);
    assert.equal(row(result,'5m').bias,row(result,'4h').bias);
  }
});

test('opposing lower structure may be a conditional pullback without invalidating intact higher context',()=>{
  for(const kinds of [['up','up','down','down'],['down','down','up','up']]){
    const {evidence,result}=read(snapshot(kinds));complete(result);
    assert.equal(result.relationship,'compatible-pullback');
    assert.equal(row(result,'4h').bias,row(result,'1h').bias);
    assert.notEqual(row(result,'15m').bias,row(result,'4h').bias);
    assert.match([result.reading,result.concern,result.setupCondition].join(' '),/possible|potential|may|could|pending|wait|requires?|unconfirmed|not confirm/i);
    assert.equal(evidence.frames['4h'].structure.trend,kinds[0]);
    assert.equal(evidence.frames['4h'].structure.lastCloseVsHigh,'below');
    assert.equal(evidence.frames['4h'].structure.lastCloseVsLow,'above');
  }
});

test('a timing-only disagreement is retained instead of becoming an aligned majority vote',()=>{
  const {result}=read(snapshot(['up','up','up','down']));complete(result);
  assert.equal(result.relationship,'mixed');assert.equal(row(result,'5m').bias,'bearish');
  assert.equal(row(result,'4h').bias,'bullish');assert.equal(row(result,'15m').bias,'bullish');
});

test('changing only 5m timing cannot rewrite the 4h assessment or its invalidation',()=>{
  const s=snapshot(['up','up','down','down']),before=read(s).result;
  s.series['5m'].candles=candles('5m','up');const after=read(s).result;
  assert.deepEqual(row(after,'4h'),row(before,'4h'));
  assert.equal(after.contextInvalidation,before.contextInvalidation);
  assert.notEqual(row(after,'5m').bias,row(before,'5m').bias);
});

test('a completed close through the latest protective swing challenges a trend without inventing a reversal',()=>{
  for(const kind of ['up','down'])for(const tf of FRAMES){
    const s=snapshot(FRAMES.map(()=>kind));challenge(s,tf);
    const {evidence,result}=read(s);complete(result);
    assert.equal(evidence.frames[tf].structure.trend,kind,'Prior confirmed swings still describe the original structure');
    assert.equal(kind==='up'?evidence.frames[tf].structure.lastCloseVsLow:evidence.frames[tf].structure.lastCloseVsHigh,kind==='up'?'below':'above');
    assert.equal(row(result,tf).bias,'mixed');
    assert.match([row(result,tf).reading,row(result,tf).verdict,row(result,tf).phase].join(' '),/challeng|broken|break|lost|violat/i);
    assert.notEqual(result.relationship,'aligned');
  }
});

test('touching a protective swing is distinct from closing through it, in both setup and context',()=>{
  for(const kind of ['up','down'])for(const tf of ['4h','15m']){
    const s=snapshot(FRAMES.map(()=>kind));
    const structure=Evidence.extract(s,'15m').frames[tf].structure;
    const level=kind==='up'?structure.swingLows.at(-1).price:structure.swingHighs.at(-1).price;
    const bar=s.series[tf].candles.at(-1);
    Object.assign(bar,{open:level,close:level,high:level+.25,low:level-.25});
    const at=read(s),field=tf==='4h'?'contextInvalidation':'setupInvalidation';
    assert.equal(at.evidence.frames[tf].structure.trend,kind);
    assert.equal(kind==='up'?at.evidence.frames[tf].structure.lastCloseVsLow:at.evidence.frames[tf].structure.lastCloseVsHigh,'at');
    assert.equal(row(at.result,tf).bias,kind==='up'?'bullish':'bearish');
    assert.doesNotMatch(at.result[field],/already|has crossed/i);
    assert.match(at.result[field],kind==='up'?/below/i:/above/i);
    assert.ok(at.result[field].includes(String(level)),`${tf} must name the actual protective swing`);
    challenge(s,tf);const broken=read(s);
    assert.equal(row(broken.result,tf).bias,'mixed');
    assert.match(broken.result[field],/already crossed/i);
    assert.doesNotMatch(broken.result[field],/would challenge/i,'An observed breach is not merely a future condition');
    assert.ok(broken.result[field].includes(String(level)));
  }
});

test('15m range condition distinguishes equality from an observed break without promising an entry',()=>{
  for(const kind of ['up','down'])for(const crossed of [false,true]){
    const s=snapshot(FRAMES.map(()=>kind)),before=Evidence.extract(s,'15m').frames['15m'];
    const bound=kind==='up'?before.prior20High:before.prior20Low;
    const close=bound+(crossed?(kind==='up'?1:-1):0);
    Object.assign(s.series['15m'].candles.at(-1),{open:close,close,high:close+.25,low:close-.25});
    const {evidence,result}=read(s);complete(result);
    assert.equal(row(result,'15m').bias,kind==='up'?'bullish':'bearish');
    assert.equal(evidence.frames['15m'].lastClosePosition,crossed?(kind==='up'?'above':'below'):'at-boundary');
    assert.match(result.setupCondition,crossed?/has already cleared/i:/has not cleared/i);
    assert.match(result.setupCondition,/not a validated entry trigger/i);
    assert.ok(result.setupCondition.includes(String(bound)),'The condition must use the prior range, excluding the latest candle');
  }
});

test('mixed higher swings stay mixed even when every lower frame trends upward',()=>{
  for(const tf of ['4h','1h']){
    const s=snapshot();s.series[tf].candles=candles(tf,'mixed');
    const {evidence,result}=read(s);complete(result);
    assert.equal(evidence.frames[tf].structure.trend,'mixed');
    assert.equal(row(result,tf).bias,'mixed');assert.equal(result.relationship,'mixed');
    assert.match([row(result,tf).phase,row(result,tf).reading].join(' '),/range|mixed/i);
  }
});

test('positive displacement and flat prices cannot substitute for sufficient confirmed pivots',()=>{
  for(const kind of ['linear','flat']){
    const {evidence,result}=read(snapshot(FRAMES.map(()=>kind)));complete(result);
    for(const tf of FRAMES){
      assert.equal(evidence.frames[tf].structure.trend,'undetermined');
      assert.equal(row(result,tf).bias,'undetermined');
      if(kind==='linear')assert.ok(evidence.frames[tf].closeDisplacement20>0);
    }
    assert.equal(result.relationship,'undetermined');
  }
});

test('each missing or stale required frame stays unavailable while fresh peers remain usable',()=>{
  for(const tf of FRAMES)for(const mode of ['missing','stale']){
    const s=snapshot();
    if(mode==='missing')delete s.series[tf];
    else s.series[tf].candles=candles(tf,'up',{cutoff:CUTOFF-SECONDS[tf]*5});
    const {evidence,result}=read(s);
    assert.equal(evidence.available,false);assert.equal(evidence.frames[tf],undefined);
    assert.equal(result.available,false);assert.equal(result.relationship,'incomplete');
    assert.deepEqual(result.frames.map(frame=>frame.timeframe),FRAMES);
    assert.equal(row(result,tf).bias,'unavailable');
    useful(row(result,tf).reading,`${mode} ${tf} reason`);
    for(const peer of FRAMES.filter(value=>value!==tf))assert.equal(row(result,peer).bias,'bullish');
  }
});

test('forming and future extremes cannot change any interpretation or confirm a protective pivot',()=>{
  const s=snapshot(['up','up','down','down']),before=read(s);
  for(const tf of FRAMES){
    const seconds=SECONDS[tf],start=Math.floor(CUTOFF/seconds)*seconds;
    for(let i=0;i<3;i++)s.series[tf].candles.push({time:start+i*seconds,open:123456789,high:987654321,low:.00001,close:876543210});
  }
  const after=read(s);assert.deepEqual(after.evidence,before.evidence);assert.deepEqual(after.result,before.result);
  assert.doesNotMatch(JSON.stringify(after.result),/123456789|987654321|876543210/);
  const now=Date.now;
  try{Date.now=()=>CUTOFF*1000+86400000;assert.deepEqual(read(s).result,before.result);}
  finally{Date.now=now;}
});

test('ARIA, accounts, cached prose and student notes cannot influence the calculated read',()=>{
  const s=snapshot(),baseline=read(s).result;
  for(const field of ['aria','account','settings','analysis','hypothesis','lessonRef','quote'])Object.defineProperty(s,field,{get(){throw Error(`Interpretation read unrelated ${field}`);}});
  for(const data of Object.values(s.series)){
    data.structure={trend:'down',reading:'FORGED_CACHED_READING'};data.error='PRIVATE_UPSTREAM_PROSE';
    data.candles.forEach(bar=>{bar.note='PRIVATE_CANDLE_NOTE';});
  }
  assert.deepEqual(read(s).result,baseline);
  const clean=Evidence.extract(snapshot(),'15m'),injected=clone(clean);
  injected.aria={score:100,reading:'FORGED_ARIA_READ'};injected.account={balance:123456789,secret:'ACCOUNT_SECRET'};
  injected.analysis={reading:'FORGED_CACHED_READING'};
  assert.deepEqual(Evidence.interpret(injected),Evidence.interpret(clean));
});

test('selected chart interval cannot replace the fixed intraday hierarchy',()=>{
  const s=snapshot(['up','up','down','down']);const baseline=read(s,'15m').result;
  for(const selected of ['1m','5m','1h','4h'])assert.deepEqual(read(s,selected).result,baseline);
});

test('a legacy two-frame saved snapshot cannot become a complete four-frame interpretation',()=>{
  const s=snapshot();delete s.profile;delete s.series['4h'];delete s.series['5m'];
  const {evidence,result}=read(s);
  assert.equal(evidence.version,1);assert.equal(evidence.available,true);
  assert.equal(result.available,false);assert.notEqual(result.relationship,'aligned');
  assert.notEqual(result.relationship,'compatible-pullback');
});
