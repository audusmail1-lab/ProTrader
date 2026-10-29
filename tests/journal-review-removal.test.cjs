const {test}=require('node:test');
const assert=require('node:assert/strict');
const Workspace=require('../static/oracle-workspace.js');
const clone=value=>JSON.parse(JSON.stringify(value));

function mounted({saved=null,confirm=()=>true}={}){
  let raw=saved?JSON.stringify(saved):null,fail=false,readFail=false,writes=0,probe=null;
  const confirmations=[],elements={owSave:{textContent:'',classList:{toggle(){}}},owTitle:{focus(){}}};
  global.localStorage={getItem:()=>{if(readFail)throw Error('Storage unavailable');return raw;},setItem(_key,value){writes++;probe?.(value);if(fail)throw Error('Storage full');raw=value;}};
  global.confirm=message=>{confirmations.push(message);return confirm(message);};
  const dialog={open:false,innerHTML:'',events:{},scrollTop:0,setAttribute(){},addEventListener(k,f){this.events[k]=f;},showModal(){this.open=true;},close(){this.open=false;}};
  const doc={body:{appendChild(){}},createElement:()=>dialog,getElementById:key=>elements[key]||null};
  delete require.cache[require.resolve('../static/oracle-workspace.js')];
  const api=require('../static/oracle-workspace.js');
  api.mount(doc,{getContext:()=>({symbol:'FIXTURE',label:'Fictional fixture',timeframe:'15m'}),getTrades:()=>[]});
  return {api,dialog,elements,confirmations,stored:()=>raw?JSON.parse(raw):null,raw:()=>raw,writes:()=>writes,
    failStorage(value=true){fail=value;},failReads(value=true){readFail=value;},replaceStorage(value){raw=JSON.stringify(value);},inspectWrite(callback){probe=callback;},
    setConfirm(callback){confirm=callback;},
    click(action,extra={}){dialog.events.click({target:{closest:()=>({dataset:{action,...extra}})}});}
  };
}

function packet(id,reading='The saved market remains inside its observed range.'){
  const snapshot={version:1,id:'snapshot-'+id,symbol:'FIXTURE',label:'Fictional '+id,asOf:1728000000,capturedAt:1728000000,dataReference:'facts-'+id,series:{}};
  return {id,snapshot,analysis:{timeframe:'15m',higherTimeframe:'1h',summary:'Original calculated summary for '+id},
    questions:[{role:'user',question:'What would change this?',text:'What would change this?',delivery:'sent'}],
    lessonRef:{lessonId:'lesson-'+id},marketReview:{reviewId:'review-'+id,at:1728000900000,snapshotId:snapshot.id,dataReference:snapshot.dataReference,reading,
      support:'Completed bars provide a visible reference.',concern:'Later continuation has not been established.',
      whatChanges:'A completed close through the saved boundary would change this view.',limits:'No news or order-flow evidence was supplied.'}};
}

function seeded(){
  const analyses=['a','b','c'].map(id=>Workspace.importAnalysis(packet(id)));
  const hypothesis=Workspace.makeHypothesis({symbol:'FIXTURE',label:'Fictional fixture',timeframe:'15m'});hypothesis.id='plan-hypothesis';
  const snapshot={version:1,id:'plan-evidence',symbol:'FIXTURE',asOf:1728000000,series:{}};
  const review={snapshotId:snapshot.id,hypothesisId:hypothesis.id,assessment:'Insufficient information',constraints:[],concerns:[],unknowns:[],facts:[],whatChanges:[],limitations:[]};
  const originAnalysis={...clone(analyses[1].analysis),marketReview:clone(analyses[1].marketReview)};
  const record=Workspace.createRecord({hypothesis,snapshot,review,originReviewId:'b',originAnalysis},'plan-record');
  const draft=id=>{const h=Workspace.makeHypothesis({symbol:'FIXTURE',label:'Fictional fixture',timeframe:'15m'});h.id=id;return{hypothesis:h,context:{symbol:'FIXTURE',label:'Fictional fixture',timeframe:'15m'},snapshot:null,step:0,originReviewId:'b',originAnalysis:clone(originAnalysis),parentId:null};};
  return {version:1,draft:draft('draft-current'),savedDrafts:[draft('draft-retained')],records:[record],savedAnalyses:analyses,
    tradeNotes:[{key:'trade-1',text:'Original reflection.',draftText:'Unfinished reflection revision.',updatedAt:'2026-10-21T10:00:00Z'}],selectedId:null,screen:'history',updatedAt:'2026-10-21T10:00:00Z'};
}

const ids=state=>state.savedAnalyses.map(item=>item.id);
const protectedData=state=>Object.fromEntries(['draft','savedDrafts','records','tradeNotes'].map(key=>[key,clone(state[key])]));
const openReviews=h=>h.api.open({history:true,section:'reviews'});

test('saved reviews expose scoped removal controls and legacy storage stays readable',()=>{
  const source=seeded(),h=mounted({saved:source});openReviews(h);
  assert.match(h.dialog.innerHTML,/data-action="clear-analyses"/);
  assert.match(h.dialog.innerHTML,/Clear saved reviews/i);
  assert.deepEqual(h.api.getState().savedAnalyses,source.savedAnalyses);
  h.click('read-analysis',{id:'b'});
  assert.match(h.dialog.innerHTML,/data-action="delete-analysis"/);
  assert.match(h.dialog.innerHTML,/Delete review/i);
  assert.equal(h.writes(),0,'Opening existing records must not rewrite storage');
});

test('cancelled single deletion and clear leave records, selection and storage unchanged',()=>{
  const h=mounted({saved:seeded(),confirm:()=>false});openReviews(h);h.click('read-analysis',{id:'b'});
  let before=h.api.getState(),raw=h.raw(),writes=h.writes();
  h.click('delete-analysis',{id:'b'});
  assert.deepEqual(h.api.getState(),before);assert.equal(h.raw(),raw);assert.equal(h.writes(),writes);
  assert.equal(h.confirmations.length,1);assert.match(h.confirmations[0],/review|journal/i);
  openReviews(h);before=h.api.getState();raw=h.raw();writes=h.writes();h.click('clear-analyses');
  assert.deepEqual(h.api.getState(),before);assert.equal(h.raw(),raw);assert.equal(h.writes(),writes);
  assert.equal(h.confirmations.length,2);
});

test('confirmed deletion removes only the selected saved review and leaves linked plans and reflections intact',()=>{
  const h=mounted({saved:seeded()});openReviews(h);h.click('read-analysis',{id:'b'});
  const before=h.api.getState(),protectedBefore=protectedData(before),writes=h.writes();
  h.click('delete-analysis',{id:'b'});
  const after=h.api.getState();assert.deepEqual(ids(after),['a','c']);
  assert.deepEqual(protectedData(after),protectedBefore);
  assert.deepEqual(after.savedAnalyses,[before.savedAnalyses[0],before.savedAnalyses[2]]);
  assert.equal(after.screen,'history');assert.notEqual(after.selectedAnalysisId,'b');
  assert.equal(h.writes(),writes+1);assert.deepEqual(ids(h.stored()),['a','c']);
  assert.match(h.dialog.innerHTML,/data-action="undo-analyses"/);
  assert.match(h.confirmations[0],/plan|trade|reflection/i,'Confirmation must explain the limited scope');
  assert.deepEqual(h.api.exportRecord(after).records,before.records);
});

test('Undo survives reload, restores original order, and keeps a review saved after deletion',()=>{
  const h=mounted({saved:seeded()});openReviews(h);const original=h.api.getState();
  h.click('delete-analysis',{id:'b'});h.api.saveAnalysis(packet('d'));
  const reloaded=mounted({saved:h.stored()});openReviews(reloaded);
  assert.match(reloaded.dialog.innerHTML,/data-action="undo-analyses"/);
  const savedLater=clone(reloaded.api.getState().savedAnalyses.find(item=>item.id==='d'));
  reloaded.click('undo-analyses');const restored=reloaded.api.getState();
  assert.deepEqual(ids(restored),['a','b','c','d']);
  assert.deepEqual(restored.savedAnalyses.slice(0,3),original.savedAnalyses);
  assert.deepEqual(restored.savedAnalyses[3],savedLater);
  assert.deepEqual(protectedData(restored),protectedData(original));
  assert.deepEqual(ids(reloaded.stored()),['a','b','c','d']);
  const writes=reloaded.writes();reloaded.click('undo-analyses');assert.equal(reloaded.writes(),writes,'One removal may be undone only once');
});

test('Clear saved reviews removes that collection only; Undo restores it around later saves',()=>{
  const h=mounted({saved:seeded()});openReviews(h);const before=h.api.getState();
  h.click('clear-analyses');assert.deepEqual(ids(h.api.getState()),[]);
  assert.deepEqual(protectedData(h.api.getState()),protectedData(before));
  assert.match(h.dialog.innerHTML,/data-action="undo-analyses"/);
  h.api.saveAnalysis(packet('d'));h.click('undo-analyses');
  assert.deepEqual(ids(h.api.getState()),['a','b','c','d']);
  assert.deepEqual(h.api.getState().savedAnalyses.slice(0,3),before.savedAnalyses);
  assert.deepEqual(protectedData(h.api.getState()),protectedData(before));
});

test('Undo never overwrites or duplicates a review re-saved with the same ID',()=>{
  const h=mounted({saved:seeded()});openReviews(h);h.click('clear-analyses');
  const replacement=h.api.saveAnalysis(packet('b','A newly saved review must take precedence over the removed copy.'));
  h.api.saveAnalysis(packet('d'));h.click('undo-analyses');
  const after=h.api.getState();assert.deepEqual(ids(after),['a','b','c','d']);
  assert.deepEqual(after.savedAnalyses.find(item=>item.id==='b'),replacement);
  assert.equal(after.savedAnalyses.filter(item=>item.id==='b').length,1);
  assert.equal(new Set(ids(after)).size,after.savedAnalyses.length);
});

test('failed deletion, clear or Undo never commits an in-memory or persistent removal',async t=>{
  for(const action of ['delete-analysis','clear-analyses','undo-analyses'])await t.test(action,()=>{
    const h=mounted({saved:seeded()});openReviews(h);
    if(action==='undo-analyses')h.click('delete-analysis',{id:'b'});
    else if(action==='delete-analysis')h.click('read-analysis',{id:'b'});
    const before=h.api.getState(),raw=h.raw();h.failStorage();
    h.click(action,{id:'b'});
    assert.deepEqual(h.api.getState(),before);assert.equal(h.raw(),raw);
    assert.match(h.dialog.innerHTML+' '+h.elements.owSave.textContent,/could not|couldn.t|not saved|unable|failed/i);
    h.failStorage(false);h.click(action,{id:'b'});
    assert.deepEqual(ids(h.api.getState()),action==='clear-analyses'?[]:action==='delete-analysis'?['a','c']:['a','b','c']);
  });
});

test('the committed UI state remains unchanged while the storage write is attempted',()=>{
  const h=mounted({saved:seeded()});openReviews(h);const before=h.api.getState();let inspected=false;
  h.inspectWrite(value=>{inspected=true;assert.deepEqual(h.api.getState(),before);assert.deepEqual(ids(JSON.parse(value)),['a','c']);});
  h.click('delete-analysis',{id:'b'});assert.equal(inspected,true);assert.deepEqual(ids(h.api.getState()),['a','c']);
});

test('unknown IDs and clearing an empty list do not consume the previous Undo batch or write storage',()=>{
  const h=mounted({saved:seeded()});openReviews(h);h.click('clear-analyses');
  const before=h.api.getState(),raw=h.raw(),writes=h.writes(),confirms=h.confirmations.length;
  h.click('delete-analysis',{id:'missing'});h.click('clear-analyses');
  assert.deepEqual(h.api.getState(),before);assert.equal(h.raw(),raw);assert.equal(h.writes(),writes);assert.equal(h.confirmations.length,confirms);
  h.click('undo-analyses');assert.deepEqual(ids(h.api.getState()),['a','b','c']);
});

test('a second confirmed removal replaces Undo with only that latest removal',()=>{
  const h=mounted({saved:seeded()});openReviews(h);
  h.click('delete-analysis',{id:'b'});h.click('delete-analysis',{id:'a'});assert.deepEqual(ids(h.api.getState()),['c']);
  h.click('undo-analyses');assert.deepEqual(ids(h.api.getState()),['a','c']);
  const writes=h.writes();h.click('undo-analyses');assert.equal(h.writes(),writes);assert.deepEqual(ids(h.api.getState()),['a','c']);
});

test('unavailable confirmation cannot delete data or replace an existing recovery batch',()=>{
  const h=mounted({saved:seeded()});openReviews(h);h.click('delete-analysis',{id:'b'});
  const before=h.api.getState(),raw=h.raw(),writes=h.writes();delete global.confirm;
  h.click('clear-analyses');assert.deepEqual(h.api.getState(),before);assert.equal(h.raw(),raw);assert.equal(h.writes(),writes);
  assert.match(h.dialog.innerHTML,/confirm|nothing.*removed|nothing.*deleted/i);
});

test('a malformed optional Undo batch cannot hide otherwise valid Journal records',()=>{
  const source=seeded();source.reviewTrash={items:'malformed recovery data'};
  const loaded=Workspace.readState({getItem:()=>JSON.stringify(source)});
  assert.deepEqual(loaded.state.savedAnalyses,source.savedAnalyses);
  assert.deepEqual(protectedData(loaded.state),protectedData(source));
  const h=mounted({saved:source});openReviews(h);const before=h.api.getState(),raw=h.raw(),writes=h.writes();
  h.click('undo-analyses');assert.deepEqual(h.api.getState(),before);assert.equal(h.raw(),raw);assert.equal(h.writes(),writes);
});

test('cross-tab changes block delete and Undo without overwriting either version of the Journal',async t=>{
  for(const action of ['delete-analysis','undo-analyses'])await t.test(action,()=>{
    const h=mounted({saved:seeded()});openReviews(h);
    if(action==='undo-analyses')h.click('delete-analysis',{id:'b'});
    const before=h.api.getState(),external=clone(h.stored());
    external.savedAnalyses.push(Workspace.importAnalysis(packet('external')));h.replaceStorage(external);
    const raw=h.raw(),writes=h.writes();h.click(action,{id:'b'});
    assert.deepEqual(h.api.getState(),before);assert.equal(h.raw(),raw);assert.equal(h.writes(),writes);
    assert.match(h.dialog.innerHTML+' '+h.elements.owSave.textContent,/reload|another|changed/i);
    const reloaded=mounted({saved:h.stored()});openReviews(reloaded);reloaded.click(action,{id:'b'});
    assert.ok(ids(reloaded.api.getState()).includes('external'));
    assert.equal(ids(reloaded.api.getState()).includes('b'),action==='undo-analyses');
  });
});

test('a storage change during confirmation prevents a stale destructive commit',()=>{
  const h=mounted({saved:seeded()});openReviews(h);const before=h.api.getState();let external;
  h.setConfirm(()=>{external=clone(h.stored());external.savedAnalyses.push(Workspace.importAnalysis(packet('external')));h.replaceStorage(external);return true;});
  const writes=h.writes();h.click('clear-analyses');
  assert.deepEqual(h.api.getState(),before);assert.deepEqual(h.stored(),external);assert.equal(h.writes(),writes);
});

test('unreadable storage blocks destructive changes without consuming Undo',()=>{
  const h=mounted({saved:seeded()});openReviews(h);h.click('delete-analysis',{id:'b'});
  const before=h.api.getState(),raw=h.raw(),writes=h.writes();h.failReads();h.click('undo-analyses');
  assert.deepEqual(h.api.getState(),before);assert.equal(h.raw(),raw);assert.equal(h.writes(),writes);
  h.failReads(false);h.click('undo-analyses');assert.deepEqual(ids(h.api.getState()),['a','b','c']);
});

test('review labels and readings remain escaped in removal and recovery UI',()=>{
  const source=seeded(),attack='<img src=x onerror="alert(1)">';source.savedAnalyses[1].snapshot.label=attack;source.savedAnalyses[1].marketReview.reading=attack+' is text, never executable markup.';
  const h=mounted({saved:source});openReviews(h);h.click('read-analysis',{id:'b'});
  assert.doesNotMatch(h.dialog.innerHTML,/<img/i);assert.match(h.dialog.innerHTML,/&lt;img/);
  h.click('delete-analysis',{id:'b'});assert.doesNotMatch(h.dialog.innerHTML,/<img/i);
  h.click('undo-analyses');h.click('read-analysis',{id:'b'});assert.doesNotMatch(h.dialog.innerHTML,/<img/i);assert.match(h.dialog.innerHTML,/&lt;img/);
});
