const {test}=require('node:test');
const assert=require('node:assert/strict');
const lesson=require('../static/lesson-practice.js');

test('the served workspace contains the native lesson dialog and its content host',()=>{
 const html=require('node:fs').readFileSync(require('node:path').join(__dirname,'../protrader_mobile.html'),'utf8');
 assert.match(html,/<script\s+defer\s+src="\/static\/lesson-practice\.js\?/);
 assert.equal((html.match(/id="lessonPracticeDialog"/g)||[]).length,1);
 assert.equal((html.match(/id="lessonPracticeContent"/g)||[]).length,1);
 assert.match(html,/<dialog\b[^>]*id="lessonPracticeDialog"[^>]*aria-labelledby="lpStepTitle"[^>]*>\s*<div id="lessonPracticeContent"><\/div>\s*<\/dialog>/);
 assert.match(html,/<button\b[^>]*id="lessonEntry"[^>]*onclick="LessonPractice\.open\(\)"/);
});

test('switching accounts clears lesson writing without overwriting either record and Learn reopens',()=>{
 const oldWindow=global.window;let raw=null,writes=0;const elements=new Map();
 const dialog={open:false,events:{},addEventListener(k,f){this.events[k]=f;},showModal(){this.open=true;},close(){this.open=false;},scrollTop:0};
 elements.set('lessonPracticeDialog',dialog);
 for(const id of ['lessonPracticeContent','lessonEntry','lpSave','lpStepTitle','lpPlanMath'])elements.set(id,{innerHTML:'',textContent:'',classList:{toggle(){}},focus(){}});
 const doc={getElementById:id=>elements.get(id)||null};
 global.window={localStorage:{getItem:()=>raw,setItem:(_k,v)=>{raw=v;writes++;}},ProTraderStorageStatus:()=> 'Saved locally; account sync is pending.'};
 try{
  delete require.cache[require.resolve('../static/lesson-practice.js')];const api=require('../static/lesson-practice.js');api.mount(doc);api.open();
  dialog.events.input({target:{dataset:{field:'observation'},type:'textarea',value:'Private observation belonging to Alice.'}});
  const alice=raw,before=writes;api.clearForAccountChange();assert.equal(dialog.open,false);assert.equal(elements.get('lessonPracticeContent').innerHTML,'');assert.equal(api.getState().attempts[0].observation,'');assert.equal(raw,alice);
  api.open();dialog.events.input({target:{dataset:{field:'observation'},value:'Late event'}});assert.equal(writes,before);
  raw=null;api.reloadStorage();assert.equal(writes,before);assert.equal(api.getState().attempts[0].observation,'');api.open();assert.equal(dialog.open,true);assert.match(elements.get('lessonPracticeContent').innerHTML,/Explain your trade idea/);assert.match(elements.get('lpSave').textContent,/sync is pending/);
  api.clearForAccountChange();raw=alice;api.reloadStorage();assert.match(api.getState().attempts[0].observation,/Alice/);assert.equal(raw,alice);
 }finally{global.window=oldWindow;delete require.cache[require.resolve('../static/lesson-practice.js')];}
});

function attempt(overrides={}) {
  return {...lesson.blankAttempt(),observation:'The last closed candle closes at 104.',idea:'The recovery above 102 may mean buyers defended the level.',evidence:['last','level'],invalidation:'A closed candle below 102 would challenge the recovery idea.',invalidationPrice:'102',action:'wait',waitReason:'There is not yet enough evidence to act on this idea.',waitTrigger:'I will review a closed candle above the previous high.',waitPrice:'106',agreement:'checks',process:'discipline',...overrides};
}
test('fictional cases contain exactly the visible closed bars and no future outcomes',()=>{
  assert.equal(lesson.CASES.length,2);
  for (const c of lesson.CASES) {
    assert.equal(c.bars.length,12);assert.equal(c.cutoff,'12:00');
    assert.equal(c.outcome,undefined);assert.equal(c.futureBars,undefined);
    for(const b of c.bars) assert.ok(b[1]>=Math.max(b[0],b[3])&&b[2]<=Math.min(b[0],b[3]));
  }
  assert.notDeepEqual(lesson.CASES[0].bars,lesson.CASES[1].bars);
});
test('a deliberate wait earns all process checks without creating a paper plan',()=>{
  const a=attempt(),review=lesson.reviewAttempt(a,0);
  assert.equal(review.ready,true);assert.equal(review.math,null);
  assert.equal(lesson.validateStep(a,1),'');assert.equal(lesson.validateStep(a,2),'');
  a.waitTrigger='Soon';assert.equal(lesson.reviewAttempt(a,0).ready,false);
});
test('predictions selected as observations and win-probability interpretations fail review',()=>{
  const a=attempt({evidence:['last','level','prediction'],agreement:'probability'}),r=lesson.reviewAttempt(a,0);
  assert.equal(r.checks.find(c=>c.id==='evidence').ok,false);
  assert.equal(r.checks.find(c=>c.id==='agreement').ok,false);
  assert.equal(r.ready,false);
});
test('the fictional paper plan checks units, dollar risk, gross ratio and structural stop',()=>{
  const a=attempt({action:'plan',side:'long',entry:'104',stop:'101',target:'110',units:'16'});
  assert.equal(lesson.reviewAttempt(a,0).ready,true);
  assert.deepEqual(lesson.planMath(a),{entry:104,stop:101,target:110,units:16,distance:3,rewardDistance:6,risk:48,reward:96,ratio:2});
  for(const invalid of [{units:'17'},{units:'1.5'},{target:'109'},{stop:'103'},{stop:'105'},{target:'103'},{invalidationPrice:'105'},{units:'Infinity'}]) {
    const r=lesson.reviewAttempt({...a,...invalid},0);assert.equal(r.checks.find(c=>c.id==='decision').ok,false,JSON.stringify(invalid));
  }
  assert.equal(lesson.reviewAttempt({...a,side:'short',entry:'104',stop:'107',target:'98',invalidationPrice:'106'},0).ready,true);
});
test('feedback and personal self-review are required before a reflection can be completed',()=>{
  const a=attempt();a.review=lesson.reviewAttempt(a,0);
  assert.notEqual(lesson.validateStep(a,3),'');
  a.selfReview=true;assert.equal(lesson.validateStep(a,3),'');
  assert.notEqual(lesson.validateStep(a,4),'');
  a.reflection='I treated a forecast as a fact and corrected it.';a.nextAction='For my next three ideas, write a verifiable observation first.';
  assert.equal(lesson.validateStep(a,4),'');
  a.review=lesson.reviewAttempt({...a,process:'profit'},0);assert.notEqual(lesson.validateStep(a,3),'');
});
test('reload restores drafts and completed reflections, recalculating fixed-rule feedback',()=>{
  const state=lesson.blankState();state.step=5;
  state.attempts[0]={...attempt(),completedAt:'2026-10-19T12:00:00.000Z',reflection:'I separated the observation from an interpretation.',nextAction:'I will write invalidation for my next three paper ideas.',review:{ready:false}};
  const storage={getItem:()=>JSON.stringify(state)};
  const loaded=lesson.readState(storage);
  assert.equal(loaded.warning,'');assert.equal(loaded.state.step,5);
  assert.equal(loaded.state.attempts[0].reflection,state.attempts[0].reflection);
  assert.equal(loaded.state.attempts[0].review.ready,true);
  state.caseIndex=1;state.step=2;state.attempts[1]=attempt({idea:'A new range case may require waiting for a break.'});
  const second=lesson.readState(storage);
  assert.equal(second.state.caseIndex,1);assert.equal(second.state.step,2);assert.equal(second.state.attempts[1].idea,state.attempts[1].idea);
});
test('unreadable or unavailable browser storage fails honestly and export retains in-memory work',()=>{
  let writes=0;
  const broken={getItem(){throw new Error('unavailable');},setItem(){writes++;throw new Error('quota');}};
  const loaded=lesson.readState(broken);assert.match(loaded.warning,/not being saved/);assert.equal(writes,0);
  const state=lesson.blankState();state.attempts[0]=attempt();
  assert.match(lesson.writeState(broken,state),/could not save/);
  const exported=lesson.record(state);assert.equal(exported.cases[0].attempt.idea,state.attempts[0].idea);assert.equal(exported.cases[0].fictional,true);
  assert.match(exported.savedIn,/no cloud/i);
  assert.match(lesson.readState({getItem:()=>'{bad JSON'}).warning,/left untouched/);
});
test('a second case cannot resume before the first record is complete',()=>{
  const state=lesson.blankState();state.caseIndex=1;state.step=3;
  const loaded=lesson.readState({getItem:()=>JSON.stringify(state)});
  assert.equal(loaded.state.caseIndex,0);assert.equal(loaded.state.step,0);
});
