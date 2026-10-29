const {test}=require('node:test');
const assert=require('node:assert/strict');
const Workspace=require('../static/oracle-workspace.js');
const clone=value=>JSON.parse(JSON.stringify(value));
function mounted(saved){
 let raw=saved?JSON.stringify(saved):null,writes=0;
 global.localStorage={getItem(){return raw;},setItem(_key,value){raw=value;writes++;}};
 const dialog={open:false,innerHTML:'',events:{},scrollTop:0,setAttribute(){},addEventListener(k,f){this.events[k]=f;},showModal(){this.open=true;},close(){this.open=false;}};
 const status={classList:{toggle(){}},focus(){}},doc={body:{appendChild(){}},createElement:()=>dialog,getElementById:id=>id==='journal-learning-panel'?null:status};
 delete require.cache[require.resolve('../static/oracle-workspace.js')];const api=require('../static/oracle-workspace.js');api.mount(doc,{getContext:()=>({symbol:'LESSON',label:'Fictional workflow fixture',timeframe:'15m'})});
 return{api,dialog,stored:()=>JSON.parse(raw),replaceRaw:value=>{raw=value?JSON.stringify(value):null;},writes:()=>writes,click:(action,id)=>dialog.events.click({target:{closest:()=>({dataset:{action,id}})}}),type:(field,value)=>dialog.events.input({target:{dataset:{field},value,type:'textarea'}})};
}
function example(){
  const hypothesis=Workspace.makeHypothesis({symbol:'LESSON',label:'Fictional workflow fixture',timeframe:'15m'});
  Object.assign(hypothesis,{observation:'The completed candle closed above the visible level.',reasoning:'I am waiting for a completed close before reassessing the evidence.',thesisLevel:100});
  hypothesis.invalidation={condition:'close-below',price:95,reason:'A completed close below the level would challenge the thesis.'};
  const snapshot={version:1,id:'evidence-original',symbol:hypothesis.symbol,asOf:1000,capturedAt:1000,series:{}};
  const review={version:1,snapshotId:snapshot.id,hypothesisId:hypothesis.id,assessment:'Supported on available evidence',constraints:[],concerns:[],unknowns:[],facts:[],whatChanges:[],limitations:[]};
  return{hypothesis,snapshot,review};
}
function later(record,id,assessment){
  const snapshot={...clone(record.snapshot),id,asOf:record.snapshot.asOf+900,capturedAt:record.snapshot.capturedAt+900};
  return{hypothesis:clone(record.hypothesis),snapshot,review:{...clone(record.review),snapshotId:id,assessment},aria:null,comparison:null,changes:['A newly completed candle changed the evidence.']};
}
test('account change clears visible Journal state without erasing storage or allowing old writes',()=>{
 const h=mounted(),{snapshot}=example();h.api.saveAnalysis({id:'alice-review',snapshot,analysis:{timeframe:'15m',summary:'Alice private interpretation'},questions:[]});
 h.api.open();h.type('observation','Alice private unfinished observation.');const alice=h.stored(),before=h.writes();
 h.api.clearForAccountChange();assert.equal(h.dialog.open,false);assert.equal(h.dialog.innerHTML,'');assert.equal(h.api.getState().savedAnalyses.length,0);assert.equal(h.api.getState().draft,null);
 h.api.open();h.type('observation','An old event must not write.');assert.throws(()=>h.api.saveAnalysis({id:'stale',snapshot,analysis:{timeframe:'15m'},questions:[]}),/account/i);
 assert.equal(h.writes(),before);assert.deepEqual(h.stored(),alice);
 h.replaceRaw(null);h.api.reloadStorage();assert.equal(h.writes(),before);assert.equal(h.api.getState().savedAnalyses.length,0);h.api.open();assert.doesNotMatch(h.dialog.innerHTML,/Alice private/);
 h.api.close();h.replaceRaw(alice);h.api.reloadStorage();assert.equal(h.api.getState().savedAnalyses[0].id,'alice-review');assert.match(h.api.getState().draft.hypothesis.observation,/Alice private/);
});
test('Oracle handoff never replaces unfinished writing until chosen, and both drafts survive reload and export',()=>{
 const h=mounted();h.api.open();h.type('observation','My earlier observation must survive the Oracle handoff.');const first=h.api.getState().draft;
 const {snapshot}=example();const saved=h.api.saveAnalysis({id:'analysis-linked',snapshot,analysis:{timeframe:'15m',summary:'Captured evidence'},questions:[]});h.api.open({originReviewId:saved.id});
 assert.equal(h.api.getState().screen,'draft-choice');assert.deepEqual(h.api.getState().draft,first);assert.match(h.dialog.innerHTML,/Keep your unfinished plan/);
 const reloaded=mounted(h.stored());assert.deepEqual(reloaded.api.getState().draft,first);reloaded.api.open({originReviewId:saved.id});reloaded.click('keep-start');
 const second=reloaded.api.getState().draft;assert.equal(second.originReviewId,saved.id);assert.deepEqual(second.snapshot,snapshot);assert.deepEqual(reloaded.api.getState().savedDrafts,[first]);
 reloaded.type('observation','My newly linked observation is independently preserved.');const edited=reloaded.api.getState().draft;reloaded.api.open({originReviewId:saved.id});assert.deepEqual(reloaded.api.getState().draft,edited);assert.equal(reloaded.api.getState().screen,'draft');
 const final=mounted(reloaded.stored());final.api.open({history:true,section:'plans'});assert.match(final.dialog.innerHTML,/Unfinished plans/);final.click('resume-saved',first.hypothesis.id);
 assert.deepEqual(final.api.getState().draft,first);assert.deepEqual(final.api.getState().savedDrafts,[edited]);const exported=final.api.exportRecord(final.api.getState());assert.deepEqual(exported.savedDrafts,[edited]);assert.deepEqual(exported.draft,first);
});
test('new-plan cancellation and legacy storage preserve existing draft without creating duplicates',()=>{
 const h=mounted();h.api.open();h.type('reasoning','An unfinished explanation that should not be overwritten.');const first=h.api.getState().draft;h.click('new');assert.equal(h.api.getState().screen,'draft-choice');h.click('resume');assert.deepEqual(h.api.getState().draft,first);assert.deepEqual(h.api.getState().savedDrafts,[]);
 h.click('new');h.api.close();assert.deepEqual(h.api.getState().draft,first);const legacy=h.stored();delete legacy.savedDrafts;const loaded=Workspace.readState({getItem:()=>JSON.stringify(legacy)});assert.equal(loaded.warning,'');assert.deepEqual(loaded.state.savedDrafts,[]);assert.deepEqual(loaded.state.draft,first);
});
test('each new evidence review permits a new reflection while original and previous decisions remain unchanged',()=>{
  const created=Workspace.createRecord(example(),'learning-record');
  const retained=Workspace.decideRecord(created,{action:'retain',reason:'I retain the hypothesis because the original completed evidence remains coherent.',reviewSnapshotId:'evidence-original',at:'2026-10-19T10:00:00Z'});
  const original=clone(retained);
  const refreshed=Workspace.appendReassessment(retained,later(retained,'evidence-later','Material concern'));
  assert.equal(refreshed.reassessments[0].decision,null);
  assert.equal(refreshed.decision.action,'retain');
  const withdrawn=Workspace.decideReassessment(refreshed,0,{action:'withdraw',reason:'The new completed close now meets my invalidation condition, so I withdraw this idea.',reviewSnapshotId:'evidence-later',at:'2026-10-19T10:15:00Z'});
  assert.deepEqual(retained,original,'Recording a later decision must not mutate the original caller');
  assert.deepEqual(withdrawn.decision,original.decision,'The first retained decision must stay retained');
  assert.equal(withdrawn.reassessments[0].decision.action,'withdraw');
  assert.equal(withdrawn.reassessments[0].decision.reviewSnapshotId,'evidence-later');
  assert.match(withdrawn.reassessments[0].reflection,/new completed close/);
  assert.throws(()=>Workspace.decideReassessment(withdrawn,0,{action:'retain',reason:'Rewriting this earlier explanation after new evidence arrived.'}),/retained/);
  const twice=Workspace.appendReassessment(withdrawn,later(withdrawn,'evidence-third','Insufficient information'));
  const revised=Workspace.decideReassessment(twice,1,{action:'revise',reason:'I will revise the idea because fresh context no longer supports the declared method.',reviewSnapshotId:'evidence-third'});
  assert.equal(revised.reassessments[0].decision.action,'withdraw');
  assert.equal(revised.reassessments[1].decision.action,'revise');
  assert.equal(revised.decision.action,'retain');
  assert.throws(()=>Workspace.decideReassessment(revised,-1,{action:'retain',reason:'An invalid review cannot receive a reflection.'}));
});
test('reload and export preserve distinct first-pass and later-review decisions plus an unfinished later reflection',()=>{
  let record=Workspace.decideRecord(Workspace.createRecord(example(),'learning-record'),{action:'retain',reason:'The initial evidence supports keeping this hypothesis under review.'});
  record=Workspace.appendReassessment(record,later(record,'evidence-later','Material concern'));
  record=Workspace.decideReassessment(record,0,{action:'withdraw',reason:'The later evidence contradicts my declared thesis, and I withdraw it.'});
  record=Workspace.appendReassessment(record,later(record,'evidence-third','Insufficient information'));
  record.reassessments[1].decisionDraft={action:'revise',reason:'Unfinished reflection about what the new evidence means.'};
  const state={version:1,draft:null,records:[record],selectedId:record.id,screen:'review',updatedAt:null};
  let saved='';const storage={setItem(_key,value){saved=value;},getItem(){return saved;}};
  assert.equal(Workspace.writeState(storage,state),'');
  const loaded=Workspace.readState(storage);assert.equal(loaded.warning,'');
  assert.deepEqual(loaded.state.records[0],record);
  const exported=Workspace.exportRecord(loaded.state);
  assert.equal(exported.records[0].decision.action,'retain');
  assert.equal(exported.records[0].reassessments[0].decision.action,'withdraw');
  assert.equal(exported.records[0].reassessments[1].decision,null);
  assert.equal(exported.records[0].reassessments[1].decisionDraft.action,'revise');
  exported.records[0].reassessments[0].reflection='Modified export';
  assert.notEqual(loaded.state.records[0].reassessments[0].reflection,'Modified export');
});
test('saved Oracle analysis remains a durable journal record before a student writes any hypothesis',()=>{
  const {snapshot}=example();
  const packet={id:'oracle-reading-1',snapshot,analysis:{version:1,timeframe:'15m',higherTimeframe:'1h',summary:'The completed bars show a bounded recovery; its continuation remains uncertain.',status:'Data available',method:'Transparent OHLC summary; not AI',facts:[{title:'Observed close',fact:'The completed candle closed at the reference.',relevance:'This is a verifiable observation.'}],alternatives:[],whatChanges:[],unknowns:['Macro events are not assessed.']},questions:[{question:'What would challenge that reading?',illustrativeResponse:'A completed close beyond the stated boundary would call for review.',label:'Illustrative response; not live AI'}],lessonRef:{lessonId:'explain-idea'}};
  const saved=Workspace.importAnalysis(packet);
  packet.snapshot.id='caller-mutated';packet.analysis.summary='Caller rewrote the analysis';packet.questions[0].question='Caller changed the question';
  assert.equal(saved.snapshot.id,'evidence-original');assert.match(saved.analysis.summary,/bounded recovery/);assert.equal(saved.questions[0].question,'What would challenge that reading?');
  const state={version:1,draft:null,records:[],savedAnalyses:[saved],selectedId:null,screen:'history',updatedAt:null};
  let text='';const storage={setItem(_key,value){text=value;},getItem(){return text;}};
  assert.equal(Workspace.writeState(storage,state),'');
  const loaded=Workspace.readState(storage);assert.equal(loaded.warning,'');assert.deepEqual(loaded.state.savedAnalyses,[saved]);assert.equal(loaded.state.records.length,0);
  const exported=Workspace.exportRecord(loaded.state);assert.deepEqual(exported.savedAnalyses,[saved]);assert.equal(exported.draft,null);
  const legacy=Workspace.readState({getItem:()=>JSON.stringify({version:1,draft:null,records:[],selectedId:null})});assert.equal(legacy.warning,'');assert.deepEqual(legacy.state.savedAnalyses,[]);
});

test('structured agent review survives Journal save, reload, export and linked plan independently of transcript',()=>{
 const h=mounted(),{snapshot}=example();snapshot.dataReference='facts-a';const marketReview={reviewId:'review-123',snapshotId:snapshot.id,dataReference:snapshot.dataReference,at:Date.now(),reading:'Agent interpretation leads this saved record.',support:'Completed bars supply observed bounds.',concern:'Later follow-through is still unknown.',whatChanges:'A completed close through the observed bound changes the view.',limits:'No news or order flow evidence was supplied.'};
 const packet={id:'saved-real-review',snapshot,analysis:{timeframe:'15m',summary:'Calculated candle summary'},questions:[],marketReview};const saved=h.api.saveAnalysis(packet);assert.deepEqual(saved.marketReview,marketReview);
 const loaded=mounted(h.stored());loaded.api.open({savedAnalysisId:saved.id});assert.ok(loaded.dialog.innerHTML.indexOf(marketReview.reading)<loaded.dialog.innerHTML.indexOf('Calculated market facts'));
 assert.deepEqual(loaded.api.exportRecord(loaded.api.getState()).savedAnalyses[0].marketReview,marketReview);
 loaded.api.open({originReviewId:saved.id});assert.deepEqual(loaded.api.getState().draft.originAnalysis.marketReview,marketReview);
 const invalid=clone(packet);invalid.marketReview.snapshotId='other';assert.equal(Workspace.importAnalysis(invalid).marketReview,null);
});

test('Journal retains four-frame review hierarchy and separate invalidations through save, reload, export and plan',()=>{
 const h=mounted(),{snapshot}=example();snapshot.profile='intraday-v1';snapshot.dataReference='facts-mtf';const mtf={profile:'intraday-v1',relationship:'compatible-pullback',governing:'4h governs context; 15m governs the setup.',setupCondition:'5m recovery is pending a completed close above the supplied high.',setupInvalidation:'15m closes below its saved setup low.',contextInvalidation:'4h closes below its confirmed higher low.',frames:['4h','1h','15m','5m'].map(timeframe=>({timeframe,reading:'An observed interpretation for this timeframe.',evidence:'Based on its separately completed candles.'}))};
 const marketReview={reviewId:'four-frames',snapshotId:snapshot.id,dataReference:snapshot.dataReference,at:Date.now(),reading:'Pullback inside a broader upward structure.',support:'The higher context still holds its confirmed low.',concern:'Lower-frame recovery remains unconfirmed.',whatChanges:'Setup and context have different change conditions.',limits:'These are lagging price observations, without news.',mtf};const saved=h.api.saveAnalysis({id:'saved-mtf',snapshot,analysis:{timeframe:'15m',profile:'intraday-v1'},questions:[],marketReview});const loaded=mounted(h.stored());loaded.api.open({savedAnalysisId:saved.id});assert.match(loaded.dialog.innerHTML,/Saved four-timeframe hierarchy/);assert.match(loaded.dialog.innerHTML,/Setup invalidated if/);assert.deepEqual(loaded.api.exportRecord(loaded.api.getState()).savedAnalyses[0].marketReview.mtf,mtf);loaded.api.open({originReviewId:saved.id});assert.deepEqual(loaded.api.getState().draft.originAnalysis.marketReview.mtf,mtf);
 const bad=clone(saved);bad.marketReview.mtf.frames[3]=bad.marketReview.mtf.frames[0];assert.equal(Workspace.importAnalysis(bad).marketReview,null);
});
