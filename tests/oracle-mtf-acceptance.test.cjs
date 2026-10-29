/* Cross-module acceptance: synthetic prices exercise integrity, not trading performance. */
const {test}=require('node:test');
const assert=require('node:assert/strict');
const Market=require('../static/oracle-market.js');
const Evidence=require('../static/oracle-evidence.js');
const Transport=require('../static/oracle-conversation.js');
const Workspace=require('../static/oracle-workspace.js');

const PROFILE='intraday-v1';
const FRAMES=['4h','1h','15m','5m'];
const AS_OF=Date.UTC(2026,9,21,12,37,30)/1000;
const clone=value=>JSON.parse(JSON.stringify(value));
const HYPOTHESIS={symbol:'R_50',timeframe:'15m',method:'continuation',action:'wait'};

function history(tf,{slope=.4,base=500,count=140,forming=true,cutoff=AS_OF}={}){
  const seconds=Market.SECONDS[tf],end=Math.floor(cutoff/seconds)*seconds;
  const wave=[0,2,4,2,0,-2,-4,-2];
  const rows=Array.from({length:count},(_,i)=>{
    const close=base+slope*i+wave[i%wave.length];
    return {time:end-(count-i)*seconds,open:close-.2,high:close+1,low:close-1,close};
  });
  if(forming)rows.push({time:end,open:10000,high:20000,low:.01,close:10000});
  return rows;
}

async function capture({rows,selected='15m',profile=PROFILE,loadRow}={}){
  const requests=[];let ticks=0,ariaReads=0;
  const byFrame=rows||Object.fromEntries(FRAMES.map((tf,i)=>[tf,history(tf,{base:500+i*250})]));
  const service=Market.createService({
    getContext:symbol=>({symbol,label:'Synthetic acceptance market',provider:'Deriv',ticker:symbol}),
    loadRow:async(context,tf,signal)=>{
      requests.push({symbol:context.symbol,timeframe:tf,signal});
      return loadRow?loadRow(context,tf,signal):byFrame[tf];
    },
    captureExecution:()=>({quote:{bid:777,ask:778},account:{openRisk:123,privateMarker:'PRIVATE_ACCOUNT_MARKER'},spec:null}),
    captureAria:()=>{ariaReads++;throw Error('First-pass capture must not consult ARIA');},
    now:()=>AS_OF*1000+(ticks++)*175,
    id:()=> 'mtf-acceptance-snapshot'
  });
  const options=profile?{profile}:{};
  const snapshot=await service.captureSnapshot({...HYPOTHESIS,timeframe:selected},options);
  const evidence=Evidence.extract(snapshot,selected);
  const pack=Transport.prepareEvidence(evidence);
  return {snapshot,evidence,pack,requests,ariaReads,rows:byFrame};
}

function assertDeepFrozen(value){
  if(value&&typeof value==='object'){
    assert.equal(Object.isFrozen(value),true);
    Object.values(value).forEach(assertDeepFrozen);
  }
}

test('four separately requested histories reach conversation with one cutoff and only completed bars',async()=>{
  const {snapshot,evidence,pack,requests,ariaReads,rows}=await capture();
  assert.deepEqual(requests.map(request=>request.timeframe),FRAMES);
  assert.equal(ariaReads,0);
  assert.equal(snapshot.profile,PROFILE);
  assert.equal(snapshot.asOf,AS_OF,'Network completion times must not move the pinned cutoff');
  assert.ok(snapshot.capturedAt>snapshot.asOf);
  assert.equal(evidence.version,2);
  assert.equal(pack.version,2);
  assert.equal(pack.profile,PROFILE);
  assert.equal(pack.available,true);
  assert.deepEqual(pack.requiredTimeframes,FRAMES);
  assert.deepEqual(Object.keys(pack.frames),FRAMES);
  assert.equal(pack.higherTimeframe,null);
  assert.equal(pack.asOf,AS_OF);
  assert.equal(pack.asOfUtc,new Date(AS_OF*1000).toISOString());
  for(const tf of FRAMES){
    const completed=rows[tf].filter(bar=>bar.time+Market.SECONDS[tf]<=AS_OF);
    const frame=pack.frames[tf];
    assert.equal(frame.lastClose,completed.at(-1).close,`${tf} must retain its own prices`);
    assert.equal(frame.closedAt,completed.at(-1).time+Market.SECONDS[tf]);
    assert.equal(frame.closedBars,completed.length);
    assert.ok(frame.closedAt<=AS_OF);
    assert.notEqual(frame.lastClose,10000,'The poisoned forming candle must be excluded');
    assert.equal(frame.prior20High,Math.max(...completed.slice(-21,-1).map(bar=>bar.high)));
    assert.equal(frame.prior20Low,Math.min(...completed.slice(-21,-1).map(bar=>bar.low)));
  }
  assert.notEqual(pack.frames['5m'].closedAt,pack.frames['15m'].closedAt);
  assert.notEqual(pack.frames['15m'].closedAt,pack.frames['4h'].closedAt);
  assertDeepFrozen(snapshot);
  assertDeepFrozen(evidence);
  assertDeepFrozen(pack);
});

test('selected chart identity never substitutes for the fixed intraday hierarchy',async()=>{
  const {pack,requests}=await capture({selected:'1m'});
  assert.equal(pack.timeframe,'1m');
  assert.deepEqual(requests.map(request=>request.timeframe),FRAMES);
  assert.deepEqual(Object.keys(pack.frames),FRAMES);
  assert.equal(pack.frames['1m'],undefined);
  assert.equal(pack.available,true);
});

test('forming prices cannot alter any completed-bar evidence or confirm a new swing',async()=>{
  const rows=Object.fromEntries(FRAMES.map(tf=>[tf,history(tf)]));
  const before=await capture({rows});
  for(const tf of FRAMES)Object.assign(rows[tf].at(-1),{open:30000,high:99999,low:.001,close:30000});
  const after=await capture({rows});
  assert.deepEqual(after.pack.frames,before.pack.frames);
  for(const tf of FRAMES){
    const frame=after.pack.frames[tf],structure=frame.structure;
    assert.equal(structure.method,'confirmed-swings-2x2-v1');
    assert.ok(structure.lookbackBars<=120);
    assert.ok(structure.through<=AS_OF);
    assert.ok(structure.swingHighs.length<=2);
    assert.ok(structure.swingLows.length<=2);
    assert.ok(structure.swingHighs.length>0&&structure.swingLows.length>0);
    for(const pivot of [...structure.swingHighs,...structure.swingLows]){
      assert.ok(pivot.confirmedAt<=frame.closedAt);
      assert.ok(pivot.confirmedAt>=pivot.time+3*Market.SECONDS[tf],`${tf} pivot requires two completed right-hand bars`);
    }
  }
});

test('a lower-timeframe decline preserves higher-timeframe upward structure for a pullback assessment',async()=>{
  const rows={
    '4h':history('4h',{slope:.6}),
    '1h':history('1h',{slope:.3}),
    '15m':history('15m',{slope:-.3}),
    '5m':history('5m',{slope:-.6})
  };
  const {pack}=await capture({rows});
  assert.equal(pack.frames['4h'].structure.trend,'up');
  assert.equal(pack.frames['1h'].structure.trend,'up');
  assert.equal(pack.frames['15m'].structure.trend,'down');
  assert.equal(pack.frames['5m'].structure.trend,'down');
  assert.equal(pack.available,true,'Disagreement is evidence, not missing data');
  const before=clone(pack.frames['4h']);
  rows['5m']=history('5m',{slope:.6});
  const changed=await capture({rows});
  assert.deepEqual(changed.pack.frames['4h'],before,'Timing data must not rewrite context facts');
  assert.equal(changed.pack.frames['5m'].structure.trend,'up');
  assert.equal(pack.mtfScore,undefined,'Independent frames must not be replaced by a vote');
  assert.equal(pack.invalidation,undefined,'Lower-frame movement does not automatically invalidate the higher frame');
});

test('each missing hierarchy frame withholds full availability while retaining the other three',async t=>{
  for(const missing of FRAMES)await t.test(missing,async()=>{
    const result=await capture({loadRow:async(_context,tf)=>{
      if(tf===missing)throw Error('Synthetic history unavailable');
      return history(tf);
    }});
    assert.equal(result.evidence.available,false);
    assert.equal(result.pack.available,false);
    assert.equal(result.pack.frames[missing],undefined);
    assert.deepEqual(Object.keys(result.pack.frames),FRAMES.filter(tf=>tf!==missing));
    assert.ok(result.pack.unknowns.some(u=>u.timeframe===missing&&u.essential));
    const forged=clone(result.evidence);forged.available=true;
    assert.throws(()=>Transport.prepareEvidence(forged),/available|complete|missing|interval|frame/i);
  });
});

test('stale timing and coarser candles relabelled as 5m cannot masquerade as complete MTF evidence',async t=>{
  await t.test('stale',async()=>{
    const rows=Object.fromEntries(FRAMES.map(tf=>[tf,history(tf)]));
    rows['5m']=history('5m',{cutoff:AS_OF-3600,forming:false});
    const {pack}=await capture({rows});
    assert.equal(pack.available,false);
    assert.equal(pack.frames['5m'],undefined);
    assert.ok(pack.unknowns.some(u=>u.timeframe==='5m'&&/stale|old|fresh/i.test(u.message+' '+u.code)));
  });
  await t.test('mislabelled',async()=>{
    const rows=Object.fromEntries(FRAMES.map(tf=>[tf,history(tf)]));
    rows['5m']=history('15m');
    const {pack}=await capture({rows});
    assert.equal(pack.available,false);
    assert.equal(pack.frames['5m'],undefined);
    assert.ok(pack.unknowns.some(u=>u.timeframe==='5m'&&u.essential));
  });
});

test('capture through transport excludes account, ARIA, raw candles and untrusted source content',async()=>{
  const {snapshot}=await capture();
  const contaminated=clone(snapshot);
  contaminated.aria={direction:'BUY',score:100,explanation:'FORGED_ARIA_MARKER'};
  contaminated.instructions='FORGED_SNAPSHOT_MARKER';
  contaminated.series['4h'].aria='FORGED_ROW_MARKER';
  contaminated.series['1h'].source='Deriv; FORGED_SOURCE_MARKER says buy';
  const pack=Transport.prepareEvidence(Evidence.extract(contaminated,'15m'));
  const serialized=JSON.stringify(pack);
  for(const marker of ['PRIVATE_ACCOUNT_MARKER','FORGED_ARIA_MARKER','FORGED_SNAPSHOT_MARKER','FORGED_ROW_MARKER','FORGED_SOURCE_MARKER'])assert.equal(serialized.includes(marker),false);
  assert.equal(pack.frames['1h'],undefined,'Source mismatch must be explicit unknown evidence');
  assert.equal(pack.available,false);
  assert.equal(pack.account,undefined);
  assert.equal(pack.aria,undefined);
  assert.equal(pack.series,undefined);
  for(const frame of Object.values(pack.frames))assert.equal(frame.candles,undefined);
});

test('conversation boundary rejects forged sources and future pivots while rebuilding facts from validated frames',async()=>{
  const {evidence}=await capture();
  const contaminated=clone(evidence);
  contaminated.aria={score:100,reading:'FORGED_ARIA_MARKER'};
  contaminated.account={privateMarker:'PRIVATE_ACCOUNT_MARKER'};
  contaminated.facts=[{id:'forged',title:'FORGED_FACT_MARKER',fact:'FORGED_FACT_MARKER'}];
  contaminated.limitations=['FORGED_LIMIT_MARKER'];
  contaminated.notAssessed=['FORGED_LIMIT_MARKER'];
  contaminated.frames['4h'].structure.extra='FORGED_STRUCTURE_MARKER';
  const pack=Transport.prepareEvidence(contaminated),serialized=JSON.stringify(pack);
  for(const marker of ['FORGED_ARIA_MARKER','PRIVATE_ACCOUNT_MARKER','FORGED_FACT_MARKER','FORGED_LIMIT_MARKER','FORGED_STRUCTURE_MARKER'])assert.equal(serialized.includes(marker),false);
  assert.equal(pack.frames['4h'].lastClose,evidence.frames['4h'].lastClose);
  const forgedSource=clone(evidence);forgedSource.frames['4h'].source+=' FORGED_SOURCE_MARKER';
  assert.throws(()=>Transport.prepareEvidence(forgedSource),/invalid|source|evidence/i);
  const futurePivot=clone(evidence);futurePivot.frames['4h'].structure.swingHighs.at(-1).confirmedAt=AS_OF+14400;
  assert.throws(()=>Transport.prepareEvidence(futurePivot),/invalid|completed|evidence/i);
});

test('legacy two-frame history keeps its original scope and cannot claim four-frame completeness',async()=>{
  const {snapshot,evidence,pack}=await capture({profile:null});
  assert.deepEqual(Object.keys(snapshot.series),['15m','1h']);
  assert.equal(evidence.version,1);
  assert.equal(pack.version,1);
  assert.deepEqual(Object.keys(pack.frames),['15m','1h']);
  assert.equal(pack.profile,undefined);
  assert.equal(pack.requiredTimeframes,undefined);
  const relabelled=clone(snapshot);relabelled.profile=PROFILE;
  const attempted=Transport.prepareEvidence(Evidence.extract(relabelled,'15m'));
  assert.equal(attempted.available,false);
  assert.equal(attempted.frames['4h'],undefined);
  assert.equal(attempted.frames['5m'],undefined);
});

function reviewFor(snapshot,withHierarchy=false){
  const review={
    reviewId:'acceptance-review',snapshotId:snapshot.id,dataReference:snapshot.dataReference,at:AS_OF*1000,
    reading:'Higher context is upward while the timing frames are pulling back.',
    support:'The observed 4h and 1h swing sequences remain higher.',
    concern:'Lower timeframes still have declining confirmed swings.',
    whatChanges:'Reassess setup failure separately from loss of the 4h context.',
    limits:'This synthetic fixture tests preservation, not model trading competence.'
  };
  if(withHierarchy)review.mtf={
    profile:PROFILE,relationship:'compatible-pullback',
    governing:'4h governs the broader context; 15m defines the setup and 5m its timing.',
    setupCondition:'Pending: a 5m completed close above its latest confirmed swing high.',
    setupInvalidation:'A 15m completed close below the stated setup low would break this setup.',
    contextInvalidation:'A 4h completed close below its context swing low would challenge the broader read.',
    frames:FRAMES.map(tf=>({timeframe:tf,reading:`${tf} has a bounded interpretation of its own swings.`,evidence:`${tf} completed-bar facts remain distinct at the saved cutoff.`}))
  };
  return review;
}

function roundTripJournal(saved){
  let raw='';const storage={setItem:(_key,value)=>{raw=value;},getItem:()=>raw};
  const state={version:1,draft:null,records:[],savedAnalyses:[saved],selectedId:null,screen:'history'};
  assert.equal(Workspace.writeState(storage,state),'');
  const loaded=Workspace.readState(storage);
  assert.equal(loaded.warning,'');
  return {loaded:loaded.state.savedAnalyses[0],exported:Workspace.exportRecord(loaded.state).savedAnalyses[0]};
}

test('legacy Journal review, identity, questions and lesson metadata survive new-module reload/export',async()=>{
  const {snapshot}=await capture({profile:null});
  const review=reviewFor(snapshot);
  const questions=[{question:'What would change that reading?',delivery:'sent',purpose:'discussion'}];
  const lessonRef={lessonId:'explain-idea',caseId:'legacy-case'};
  const saved=Workspace.importAnalysis({id:'legacy-saved-review',snapshot,analysis:{version:1,timeframe:'15m',higherTimeframe:'1h',summary:'Original two-frame summary'},questions,lessonRef,marketReview:review});
  const {loaded,exported}=roundTripJournal(saved);
  assert.deepEqual(loaded,saved);
  assert.deepEqual(exported.marketReview,review);
  assert.deepEqual(exported.questions,questions);
  assert.deepEqual(exported.lessonRef,lessonRef);
  assert.deepEqual(exported.snapshot,snapshot);
  assert.equal(exported.marketReview.mtf,undefined);
  exported.marketReview.reading='Mutated export';
  assert.equal(loaded.marketReview.reading,review.reading);
});

test('an optional model hierarchy cannot upgrade a legacy two-frame Journal review',async()=>{
  const {snapshot,pack}=await capture({profile:null});
  const review=reviewFor(snapshot,true);
  const saved=Workspace.importAnalysis({id:'legacy-with-extra-model-fields',snapshot,analysis:{version:1,timeframe:'15m',higherTimeframe:'1h'},questions:[],marketReview:review});
  assert.ok(saved.marketReview,'The valid original five-field review remains usable');
  assert.equal(saved.marketReview.reading,review.reading);
  assert.equal(saved.marketReview.mtf,undefined,'Two-frame saved evidence must not be presented as a four-frame review');
  const {loaded,exported}=roundTripJournal(saved);
  assert.equal(loaded.marketReview.mtf,undefined);
  assert.equal(exported.marketReview.mtf,undefined);
  const context=Transport.prepareDiscussionContext({snapshotId:snapshot.id,dataReference:snapshot.dataReference,review,messages:[]},pack);
  assert.equal(context.review.mtf,undefined);
});

test('hierarchy and separate setup/context invalidations survive Journal and discussion handoff',async()=>{
  const {snapshot,pack}=await capture();
  const review=reviewFor(snapshot,true);
  const saved=Workspace.importAnalysis({id:'mtf-saved-review',snapshot,analysis:{version:2,profile:PROFILE,timeframe:'15m',summary:review.reading},questions:[],marketReview:review});
  const {loaded,exported}=roundTripJournal(saved);
  assert.deepEqual(loaded.marketReview,review);
  assert.deepEqual(exported.marketReview,review);
  const context=Transport.prepareDiscussionContext({snapshotId:snapshot.id,dataReference:snapshot.dataReference,review:loaded.marketReview,messages:[]},pack);
  assert.deepEqual(context.review.mtf,review.mtf);
  assert.notEqual(context.review.mtf.setupInvalidation,context.review.mtf.contextInvalidation);
  assert.equal(context.review.mtf.relationship,'compatible-pullback');
  assert.throws(()=>Transport.prepareDiscussionContext({snapshotId:snapshot.id,dataReference:'different-cutoff',review,messages:[]},pack),/different market evidence/);
  const mismatched=clone(review);mismatched.dataReference='different-cutoff';
  assert.equal(Workspace.importAnalysis({id:'wrong-evidence',snapshot,analysis:{summary:'Must not adopt another snapshot review'},questions:[],marketReview:mismatched}).marketReview,null);
});

test('a saved intraday review opens a 15m plan with 1h context regardless of its chart anchor',async t=>{
  for(const selected of ['1m','4h'])await t.test(selected,async()=>{
    const {snapshot}=await capture({selected});
    const previousStorage=global.localStorage;let raw=null;
    global.localStorage={getItem:()=>raw,setItem:(_key,value)=>{raw=value;}};
    try{
      const dialog={open:false,innerHTML:'',events:{},scrollTop:0,setAttribute(){},addEventListener(k,f){this.events[k]=f;},showModal(){this.open=true;},close(){this.open=false;}};
      const status={classList:{toggle(){}},focus(){}};
      const doc={body:{appendChild(){}},createElement:()=>dialog,getElementById:id=>id==='journal-learning-panel'?null:status};
      delete require.cache[require.resolve('../static/oracle-workspace.js')];
      const api=require('../static/oracle-workspace.js');
      api.mount(doc,{getContext:()=>({symbol:snapshot.symbol,label:snapshot.label,timeframe:selected})});
      const marketReview=reviewFor(snapshot,true);
      const saved=api.saveAnalysis({id:'plan-handoff-'+selected,snapshot,analysis:{profile:PROFILE,timeframe:selected,summary:marketReview.reading},questions:[],marketReview});
      api.open({originReviewId:saved.id});
      const draft=api.getState().draft;
      assert.equal(draft.hypothesis.timeframe,'15m');
      assert.equal(draft.context.timeframe,'15m');
      assert.equal(draft.originAnalysis.timeframe,selected,'Original selected-chart identity remains historical metadata');
      assert.deepEqual(draft.snapshot,snapshot,'The plan must retain all captured evidence, not synthesize 1d or 1m bars');
      assert.deepEqual(Object.keys(draft.snapshot.series),FRAMES);
      assert.deepEqual(draft.originAnalysis.marketReview,marketReview);
      assert.match(dialog.innerHTML,/15m plan with 1h context/);
      assert.deepEqual(api.exportRecord(api.getState()).draft,draft);
    }finally{
      if(previousStorage===undefined)delete global.localStorage;else global.localStorage=previousStorage;
    }
  });
});
