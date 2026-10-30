const {test}=require('node:test');
const assert=require('node:assert/strict');
const Evidence=require('../static/oracle-evidence.js');
const asOf=1800000000;
function snapshot(id='snapshot-a'){
 const bars=tf=>{const sec=tf==='15m'?900:3600,end=Math.floor(asOf/sec)*sec;return Array.from({length:40},(_,i)=>({time:end-(40-i)*sec,open:100+i,high:102+i,low:99+i,close:101+i}));};
 return {id,symbol:'R_50',label:'Vol 50',provider:'Deriv',asOf,capturedAt:asOf+1,dataReference:'fnv1a32-'+id,series:Object.fromEntries(['15m','1h'].map(tf=>[tf,{status:'ready',source:'Deriv',capturedAt:asOf+1,candles:bars(tf)}]))};
}
function harness(saved){
 let writeCount=0;let callbacks,disconnected=0,stored=saved?JSON.stringify(saved):null,send=async()=>{},sendAttachment=async()=>{},connect=null,storageFailure=false,confirmation=()=>true;const confirmations=[],connections=[];
 global.OracleEvidence=Evidence;global.OracleConversation={create(c){callbacks=c;return{status:async()=>({configured:true}),connect:async(options={})=>{connections.push(options);c.onStatus({state:'connecting',mode:options.mode||'text'});if(connect)await connect();c.onStatus({state:'connected',mode:options.mode||'text'});},disconnect:async()=>{disconnected++;c.onStatus({state:'disconnected'});},send:(...args)=>send(...args),sendAttachment:(...args)=>sendAttachment(...args)};}};
 global.localStorage={getItem:()=>stored,setItem(_key,value){writeCount++;if(storageFailure)throw Error('Storage unavailable');stored=value;}};
 global.confirm=message=>{confirmations.push(message);return confirmation(message);};
 const element=()=>({innerHTML:'',open:false,events:{},addEventListener(k,f){this.events[k]=f;},setAttribute(){},showModal(){this.open=true;},close(){this.open=false;}});
 const panel=element(),dialog=element(),doc={body:{appendChild(){}},createElement:()=>dialog,getElementById:id=>id==='oracle-panel'?panel:null};
 let journalSaves=[];const ctx={symbol:'R_50',label:'Vol 50',timeframe:'15m'};let capture=async()=>snapshot();
 delete require.cache[require.resolve('../static/oracle-analyst.js')];const api=require('../static/oracle-analyst.js');
 api.mount(doc,{getContext:()=>ctx,captureSnapshot:(...args)=>capture(...args),saveToJournal:p=>{journalSaves.push(p);return p;},openJournal(){}});
 const input={id:'oaQuestionPanel',value:'',focus(){},setSelectionRange(){},matches:()=>true,closest:()=>panel};panel.querySelector=()=>input;dialog.querySelector=()=>input;
 return{api,ctx,doc,panel,dialog,input,journalSaves,writes:()=>writeCount,setSaved:value=>stored=value===null?null:JSON.stringify(value),confirmations,connections,setConfirmation:f=>confirmation=f,setStorageFailure:value=>storageFailure=value,setConnect:f=>connect=f,key:(options={},expanded=false)=>{const e={target:input,key:'Enter',preventDefault(){this.prevented=true;},stopPropagation(){},...options};(expanded?dialog:panel).events.keydown(e);return e;},stored:()=>JSON.parse(stored),setSend:f=>send=f,setAttachment:f=>sendAttachment=f,setCapture:f=>capture=f,callbacks:()=>callbacks,disconnects:()=>disconnected,type:text=>{input.value=text;panel.events.input({target:{matches:()=>true,value:text}});},click:(oa,id)=>panel.events.click({target:{closest:()=>({dataset:{oa,id},closest:()=>panel})}})};
}
const tick=()=>new Promise(resolve=>setImmediate(resolve));
test('same-selection events preserve a pending question, connected session and private draft',async()=>{
 const h=harness();await h.api.refresh();h.type('Sent question');h.click('ask');await tick();h.type('Private draft');
 const before=h.api.getPacket(),disconnects=h.disconnects();h.api.contextChanged();await tick();assert.equal(h.disconnects(),disconnects);assert.deepEqual(h.api.getPacket(),before);
 h.callbacks().onMessage({role:'assistant',text:'Reply to sent question'});assert.equal(h.api.getPacket().questions.find(q=>q.text==='Sent question').answerState,'answered');assert.equal(h.api.getPacket().draft,'Private draft');
 h.click('disconnect');
});
test('chart change requires explicit old-review or selected-chart choice and keeps drafts scoped',async()=>{
 const h=harness(localHistory());await tick();const sends=[];h.setSend(async text=>sends.push(text));h.ctx.symbol='frxEURUSD';h.ctx.label='EUR/USD';h.api.contextChanged();
 h.type('Keep with original market');h.click('ask');await tick();assert.equal(sends.length,0);assert.match(h.panel.innerHTML,/Choose what to discuss/);
 h.click('continue-saved');h.click('ask');await tick();assert.equal(sends[0],'Keep with original market');assert.equal(h.callbacks().getEvidence().symbol,'R_50');
 h.callbacks().onMessage({role:'assistant',text:'Answer about Vol 50'});h.type('Original-market draft');
 h.ctx.symbol='frxGBPUSD';h.ctx.label='GBP/USD';h.api.contextChanged();h.click('ask');await tick();assert.equal(sends.length,1);
 h.setCapture(async()=>({...snapshot('new-chart'),symbol:'frxGBPUSD',label:'GBP/USD'}));h.click('refresh');await tick();assert.equal(h.api.getPacket().snapshot.symbol,'frxGBPUSD');assert.equal(h.api.getPacket().questions.length,0);assert.equal(h.api.getHistory()[0].draft,'Original-market draft');
});
test('discussion memory includes sent replies and matching review but never private drafts or unsent questions',async()=>{
 const h=harness(localHistory());await tick();h.type('Actually sent');h.click('ask');await tick();h.callbacks().onMessage({role:'assistant',text:'Actual answer'});h.type('Keep private');h.click('keep');h.type('Unsent draft');
 const context=h.callbacks().getDiscussionContext();assert.equal(context.snapshotId,'current');assert.equal(context.review.reading,reviewFields.reading);assert.deepEqual(context.messages.map(q=>q.text),['Actually sent','Actual answer']);assert.doesNotMatch(JSON.stringify(context),/Keep private|Unsent draft|old-a/);
 h.click('connect-voice');await tick();assert.equal(h.connections.at(-1).mode,'voice');assert.equal(h.connections.at(-1).purpose,'discussion');assert.equal(h.api.getPacket().draft,'Unsent draft');h.click('disconnect');
});
test('fresh market review marks connect and send independent of discussion',async()=>{
 const h=harness(localHistory());await tick();const calls=[];h.setSend(async(...args)=>calls.push(args));h.click('review');await tick();assert.equal(h.connections.at(-1).purpose,'review');assert.equal(calls[0][1].purpose,'review');h.click('cancel-review');h.click('disconnect');
});
test('waiting blocks duplicate sends; answer or explicit stop preserves recoverable question',async()=>{
 const h=harness();await h.api.refresh();const sent=[];h.setSend(async text=>sent.push(text));h.type('First question');h.click('ask');await tick();assert.match(h.panel.innerHTML,/Waiting for Oracle/);
 h.type('Next draft');h.key();await tick();assert.deepEqual(sent,['First question']);h.click('stop-reply');await tick();const first=h.api.getPacket().questions.find(q=>q.text==='First question');assert.equal(first.answerState,'interrupted');assert.equal(h.api.getPacket().draft,'Next draft');
 h.callbacks().onMessage({role:'assistant',text:'Late reply after stop'});assert.doesNotMatch(JSON.stringify(h.api.getPacket()),/Late reply after stop/);h.click('retry',first.id);await tick();assert.deepEqual(sent,['First question','First question']);h.callbacks().onMessage({role:'assistant',text:'Confirmed answer'});assert.equal(h.api.getPacket().questions.find(q=>q.id===first.id).answerState,'answered');h.click('disconnect');
});
test('voice events update one transcript, retain next-question wait, and produce new Journal revision',async()=>{
 const h=harness();await h.api.refresh();h.click('connect-voice');await tick();h.callbacks().onModeChange({mode:'speaking'});assert.match(h.panel.innerHTML,/Oracle is speaking/);
 h.callbacks().onMessage({role:'assistant',text:'Original voice answer',eventId:0});h.click('journal');const first=h.journalSaves.at(-1);
 h.callbacks().onMessage({role:'user',text:'New spoken question',eventId:1});h.callbacks().onInterruption({eventId:0});assert.equal(h.api.getPacket().questions.find(q=>q.text==='New spoken question').answerState,'waiting');
 h.callbacks().onResponseCorrection({eventId:0,originalText:'Original voice answer',correctedText:'Corrected voice answer'});h.click('journal');const revised=h.journalSaves.at(-1);assert.notEqual(first.id,revised.id);assert.match(JSON.stringify(revised),/Corrected voice answer/);assert.doesNotMatch(JSON.stringify(revised),/Original voice answer/);
 h.callbacks().onMessage({role:'assistant',text:'Answer to next question',eventId:2});h.callbacks().onMessage({role:'assistant',text:'Answer to next question',eventId:2});assert.equal(h.api.getPacket().questions.filter(q=>q.eventId==='2').length,1);assert.equal(h.api.getPacket().questions.find(q=>q.text==='New spoken question').answerState,'answered');
 h.click('connect-text');await tick();h.callbacks().onResponseCorrection({eventId:0,correctedText:'Stale correction'});assert.doesNotMatch(JSON.stringify(h.api.getPacket()),/Stale correction/);h.click('disconnect');
});
test('voice correction without IDs matches exactly one current-session answer',async()=>{
 const h=harness();await h.api.refresh();h.click('connect-voice');await tick();h.callbacks().onMessage({role:'assistant',text:'Unique answer'});h.callbacks().onResponseCorrection({originalText:'Unique answer',correctedText:'Shortened answer'});assert.ok(h.api.getPacket().questions.some(q=>q.text==='Shortened answer'&&q.corrected));
 h.callbacks().onMessage({role:'assistant',text:'Ambiguous answer'});h.callbacks().onMessage({role:'assistant',text:'Ambiguous answer'});h.callbacks().onResponseCorrection({originalText:'Ambiguous answer',correctedText:'Do not guess'});assert.doesNotMatch(JSON.stringify(h.api.getPacket()),/Do not guess/);h.click('disconnect');
});
test('unknown interruption ID cannot change the latest voice answer or the next question wait',async()=>{
 const h=harness();await h.api.refresh();h.click('connect-voice');await tick();h.callbacks().onMessage({role:'assistant',text:'Known answer',eventId:4});h.callbacks().onModeChange({mode:'speaking'});h.callbacks().onMessage({role:'user',text:'Next question',eventId:5});const before=h.api.getPacket();
 h.callbacks().onInterruption({eventId:999});assert.deepEqual(h.api.getPacket(),before);assert.equal(h.api.getPacket().questions.find(q=>q.text==='Next question').answerState,'waiting');h.click('disconnect');
});
test('image question precedes immediate reply, prevents switching during upload, and failures never retry as text',async()=>{
 const h=harness();await h.api.refresh();h.click('connect-text');await tick();let resolve;h.setAttachment(()=>new Promise(r=>resolve=r));h.type('Explain image');
 const image=()=>h.panel.events.change({target:{files:[{name:'chart.png',type:'image/png',size:20}],matches:()=>true,closest:()=>h.panel}});image();await tick();const count=h.connections.length;h.click('connect-voice');h.api.contextChanged();await tick();assert.equal(h.connections.length,count);
 h.callbacks().onMessage({role:'assistant',text:'Immediate image answer'});resolve({snapshotId:'snapshot-a',name:'chart.png',type:'image/png',size:20});await tick();let q=h.api.getPacket().questions.find(q=>q.attachment);assert.equal(q.delivery,'sent');assert.equal(q.answerState,'answered');assert.ok(h.panel.innerHTML.indexOf('Chart image: chart.png')<h.panel.innerHTML.indexOf('Immediate image answer'));
 h.setAttachment(async()=>{throw Error('Image failed');});image();await tick();q=h.api.getPacket().questions.filter(q=>q.attachment).at(-1);assert.equal(q.delivery,'failed');assert.doesNotMatch(h.panel.innerHTML,new RegExp('data-oa="retry" data-id="'+q.id+'"'));assert.match(h.panel.innerHTML,/Select the image again/);h.click('disconnect');
});
test('reload converts an unfinished wait to interrupted without automatically sending',async()=>{
 const h=harness();await h.api.refresh();h.type('Pending question');h.click('ask');await tick();const saved=h.stored();h.click('disconnect');const loaded=harness(saved);await tick();assert.equal(loaded.api.getPacket().questions.find(q=>q.text==='Pending question').answerState,'interrupted');assert.equal(loaded.connections.length,0);assert.match(loaded.panel.innerHTML,/Ask again/);
});
test('idle status/error callbacks do not overwrite unreadable saved data',async()=>{
 const bad={version:2,active:{bad:'KEEP_ME'}};const h=harness(bad);await tick();h.callbacks().onStatus({state:'disconnected'});h.callbacks().onError('Unavailable');assert.deepEqual(h.stored(),bad);
});
test('late cancelled review cannot complete the wait for a normal follow-up',async()=>{
 const h=harness();await h.api.refresh();const id=await reviewRequest(h);h.click('cancel-review');h.type('My actual follow-up');h.click('ask');await tick();
 h.callbacks().onMessage({role:'assistant',text:JSON.stringify({reviewId:id,...reviewFields})});let q=h.api.getPacket().questions.find(q=>q.text==='My actual follow-up');assert.equal(q.answerState,'waiting');assert.equal(h.api.getPacket().marketReview,undefined);assert.doesNotMatch(JSON.stringify(h.callbacks().getDiscussionContext().messages),/Supporting evidence/);
 h.callbacks().onMessage({role:'assistant',text:'Actual follow-up answer'});q=h.api.getPacket().questions.find(q=>q.text==='My actual follow-up');assert.equal(q.answerState,'answered');h.click('disconnect');
});
test('analyst recomputes cached summary and rejects transcript entries bound to other evidence',()=>{
 const s=snapshot(),h=harness({id:'read-a',snapshot:s,analysis:{timeframe:'15m',summary:'FORGED GUARANTEED RESULT'},questions:[{role:'assistant',text:'A different snapshot answer',snapshotId:'other',dataReference:'other'}]});
 assert.equal(h.api.getPacket().analysis.status,'Data available');assert.doesNotMatch(h.api.getPacket().analysis.summary,/FORGED/);assert.equal(h.api.getPacket().questions.length,0);
});
test('timeframe change during capture does not apply old context to new selection',async()=>{
 const h=harness();let release;h.setCapture(()=>new Promise(resolve=>release=resolve));const pending=h.api.refresh();await tick();h.ctx.timeframe='1h';release(snapshot());await pending;assert.equal(h.api.getPacket(),null);
});
test('refresh disconnects and rejects a delayed reply about the previous frozen snapshot',async()=>{
 const h=harness();await h.api.refresh();h.click('connect-text');await tick();h.callbacks().onMessage({role:'assistant',text:'Reply about first evidence'});
 assert.equal(h.api.getPacket().questions.filter(q=>q.role==='assistant').length,1);assert.equal(h.api.getPacket().questions[0].snapshotId,'snapshot-a');
 h.setCapture(async()=>snapshot('snapshot-b'));await h.api.refresh();h.callbacks().onMessage({role:'assistant',text:'Late first-evidence reply'});
 assert.equal(h.api.getPacket().snapshot.id,'snapshot-b');assert.equal(h.api.getPacket().questions.length,0);assert.ok(h.disconnects()>=2);
 assert.ok(h.api.getHistory()[0].questions.some(q=>q.text==='Reply about first evidence'));assert.doesNotMatch(JSON.stringify(h.api.getHistory()),/Late first-evidence/);
});
test('draft survives redraw, review-my-idea, evidence refresh and reload in the original discussion',async()=>{
 const h=harness();await h.api.refresh();h.type('My own unfinished question');h.api.render();h.click('idea');
 assert.equal(h.api.getPacket().draft,'My own unfinished question');assert.match(h.panel.innerHTML,/My own unfinished question/);
 h.setCapture(async()=>snapshot('next'));await h.api.refresh();assert.equal(h.api.getPacket().draft,'');assert.equal(h.api.getHistory()[0].draft,'My own unfinished question');
 const loaded=harness(h.stored());loaded.click('history','snapshot-a');await tick();assert.equal(loaded.api.getPacket().draft,'My own unfinished question');
});
test('failed questions stay retryable without duplication; ordinary replies remain in discussion and reconnect starts a new session',async()=>{
 const h=harness();await h.api.refresh();h.click('connect-text');await tick();h.setSend(async()=>{throw Error('Test transport unavailable');});h.type('Please explain the evidence');h.click('ask');await tick();
 let q=h.api.getPacket().questions.find(q=>q.role==='user');assert.equal(q.delivery,'failed');assert.equal(h.api.getPacket().draft,'Please explain the evidence');
 h.setSend(async()=>{});h.click('retry',q.id);await tick();q=h.api.getPacket().questions.find(q=>q.role==='user');assert.equal(q.delivery,'sent');assert.equal(h.api.getPacket().questions.filter(q=>q.role==='user').length,1);
 h.callbacks().onMessage({role:'assistant',text:'This is a verified mock reply'});assert.equal(h.api.getPacket().marketReview,undefined);assert.match(h.panel.innerHTML,/No agent review has been generated/);assert.match(h.panel.innerHTML,/This is a verified mock reply/);
 h.click('disconnect');await tick();h.click('connect-text');await tick();assert.equal(h.api.getPacket().questions.filter(q=>q.role==='session').length,2);assert.deepEqual(h.callbacks().getDiscussionContext().messages.map(q=>q.text),['Please explain the evidence','This is a verified mock reply']);
});
test('analyst and conversational extractor agree on rejected interval integrity',()=>{
 const h=harness(),s=snapshot();s.series['15m'].candles[2].time+=1;
 assert.equal(Evidence.extract(s,'15m').available,false);assert.equal(h.api.analyze(s,'15m').status,'Insufficient information');
});

const reviewFields={reading:'Price remains inside the observed range.',support:'Both supplied frames describe completed closes.',concern:'Displacement alone does not establish trend.',whatChanges:'A completed close beyond the saved bound changes the range reading.',limits:'News and order flow are not included in this snapshot.'};
async function reviewRequest(h){let sent;h.setSend(async text=>{sent=text;});h.click('review');await tick();assert.ok(sent,'explicit review was sent');return JSON.parse(sent.slice(sent.indexOf('{'))).reviewId;}
test('review action is explicit, uses a fresh session and preserves the composer draft',async()=>{
 const h=harness();await h.api.refresh();let sends=0;h.setSend(async()=>{sends++;});h.click('connect-text');await tick();
 h.callbacks().onMessage({role:'assistant',text:'Hello. What would you like to explore?'});assert.equal(sends,0);assert.equal(h.api.getPacket().marketReview,undefined);
 h.type('My unfinished question');const id=await reviewRequest(h);assert.equal(h.api.getPacket().draft,'My unfinished question');assert.equal(h.api.getPacket().connectionCount,2);
 h.callbacks().onMessage({role:'assistant',text:'Are you still there?'});assert.equal(h.api.getPacket().marketReview,undefined);
 h.callbacks().onMessage({role:'assistant',text:JSON.stringify({reviewId:'wrong',...reviewFields})});assert.equal(h.api.getPacket().marketReview,undefined);
 h.callbacks().onMessage({role:'assistant',text:JSON.stringify({reviewId:id,...reviewFields})});assert.equal(h.api.getPacket().marketReview.reading,reviewFields.reading);
 const html=h.panel.innerHTML;assert.ok(html.indexOf(reviewFields.reading)<html.indexOf('Market facts'));assert.ok(html.indexOf('aria-label="Discuss this reading"')<html.indexOf('Market facts'));assert.equal(h.api.getPacket().draft,'My unfinished question');
 h.callbacks().onMessage({role:'assistant',text:'Connection check: R_50, 15m, 1h.'});assert.equal(h.api.getPacket().marketReview.reading,reviewFields.reading);
 h.click('disconnect');await tick();
});
test('stopped or disconnected review cannot replace previous assessment and does not auto-retry',async()=>{
 const h=harness();await h.api.refresh();let id=await reviewRequest(h);h.callbacks().onMessage({role:'assistant',text:JSON.stringify({reviewId:id,...reviewFields})});
 id=await reviewRequest(h);h.click('cancel-review');h.callbacks().onMessage({role:'assistant',text:JSON.stringify({reviewId:id,...reviewFields,reading:'A late cancelled review should not lead.'})});assert.equal(h.api.getPacket().marketReview.reading,reviewFields.reading);
 id=await reviewRequest(h);h.callbacks().onStatus({state:'disconnected'});h.callbacks().onMessage({role:'assistant',text:JSON.stringify({reviewId:id,...reviewFields,reading:'A disconnected answer must not replace it.'})});assert.equal(h.api.getPacket().marketReview.reading,reviewFields.reading);assert.match(h.panel.innerHTML,/connection ended before a complete review/);
});
test('review state survives reload but is rejected for different evidence or invalid fields',async()=>{
 const h=harness();await h.api.refresh();const id=await reviewRequest(h);h.callbacks().onMessage({role:'assistant',text:JSON.stringify({reviewId:id,...reviewFields})});
 const saved=h.stored();let loaded=harness(saved);assert.equal(loaded.api.getPacket().marketReview.reading,reviewFields.reading);
 saved.active.marketReview.dataReference='wrong-evidence';loaded=harness(saved);assert.equal(loaded.api.getPacket().marketReview,null);
 saved.active.marketReview.dataReference=saved.active.snapshot.dataReference;saved.active.marketReview.support='';loaded=harness(saved);assert.equal(loaded.api.getPacket().marketReview,null);
});
test('new evidence cancels a pending review, retains the earlier assessment and rejects late response',async()=>{
 const h=harness();await h.api.refresh();let id=await reviewRequest(h);h.callbacks().onMessage({role:'assistant',text:JSON.stringify({reviewId:id,...reviewFields})});
 id=await reviewRequest(h);h.setCapture(async()=>snapshot('next'));await h.api.refresh();h.callbacks().onMessage({role:'assistant',text:JSON.stringify({reviewId:id,...reviewFields})});
 assert.equal(h.api.getPacket().marketReview,undefined);assert.equal(h.api.getPacket().questions.length,0);assert.equal(h.api.getHistory()[0].marketReview.reading,reviewFields.reading);
});
test('review send failure preserves draft and earlier assessment; incomplete or untagged replies are not promoted',async()=>{
 const h=harness();await h.api.refresh();let id=await reviewRequest(h);
 h.callbacks().onMessage({role:'assistant',text:JSON.stringify({reviewId:id,reading:'Missing the other sections'})});assert.equal(h.api.getPacket().marketReview,undefined);
 h.callbacks().onMessage({role:'assistant',text:JSON.stringify({...reviewFields})});assert.equal(h.api.getPacket().marketReview,undefined);
 h.callbacks().onMessage({role:'assistant',text:JSON.stringify({reviewId:id,...reviewFields,reading:'<img src=x onerror=alert(1)> remains a string.'})});assert.doesNotMatch(h.panel.innerHTML,/<img src=x/);assert.match(h.panel.innerHTML,/&lt;img/);
 h.type('Keep this draft');h.setSend(async()=>{throw Error('Provider not available');});h.click('review');await tick();assert.equal(h.api.getPacket().draft,'Keep this draft');assert.ok(h.api.getPacket().marketReview);assert.match(h.panel.innerHTML,/Provider not available/);
});

test('Journal revision identity changes when a capped transcript receives a new review',async()=>{
 const h=harness();await h.api.refresh();let id=await reviewRequest(h);h.callbacks().onMessage({role:'assistant',text:JSON.stringify({reviewId:id,...reviewFields})});
 for(let i=0;i<45;i++)h.callbacks().onMessage({role:'assistant',text:'Ordinary follow-up '+i});h.click('journal');const first=h.journalSaves.at(-1);h.click('journal');assert.equal(first.id,h.journalSaves.at(-1).id);
 id=await reviewRequest(h);h.callbacks().onMessage({role:'assistant',text:JSON.stringify({reviewId:id,...reviewFields,reading:'A new explicit assessment of the same saved evidence.'})});h.click('journal');const second=h.journalSaves.at(-1);
 assert.equal(first.questions.length,40);assert.equal(second.questions.length,40);assert.notEqual(first.id,second.id);assert.equal(second.marketReview.reviewId,id);
});

test('Enter connects and sends once; Shift+Enter, composition and repeat do not submit in either view',async()=>{
 for(const expanded of [false,true]){
  const h=harness();await h.api.refresh();const sent=[];h.setSend(async text=>sent.push(text));h.type('Explain this saved evidence.');
  assert.equal(h.key({shiftKey:true},expanded).prevented,undefined);assert.equal(h.key({isComposing:true},expanded).prevented,undefined);assert.equal(h.key({keyCode:229},expanded).prevented,undefined);h.key({repeat:true},expanded);await tick();assert.equal(sent.length,0);
  assert.equal(h.key({},expanded).prevented,true);h.key({},expanded);await tick();assert.deepEqual(sent,['Explain this saved evidence.']);assert.equal(h.api.getPacket().draft,'');assert.equal(h.api.getPacket().questions.filter(q=>q.role==='user').length,1);
 }
});
test('connect-and-ask captures original text while edits during connection remain unsent',async()=>{
 const h=harness();await h.api.refresh();let release;h.setConnect(()=>new Promise(resolve=>release=resolve));const sent=[];h.setSend(async text=>sent.push(text));h.type('Original explicit question');h.click('ask');await tick();h.type('A new unfinished draft');h.click('ask');assert.equal(sent.length,0);release();await tick();
 assert.deepEqual(sent,['Original explicit question']);assert.equal(h.api.getPacket().draft,'A new unfinished draft');assert.equal(h.api.getPacket().questions.filter(q=>q.role==='user').length,1);
});
test('failed connection retains an unsent question and reconnect retry sends it once',async()=>{
 const h=harness();await h.api.refresh();h.setConnect(async()=>{throw Error('Key access denied');});const sent=[];h.setSend(async text=>sent.push(text));h.type('My question survives failure');h.click('ask');await tick();assert.equal(sent.length,0);assert.equal(h.api.getPacket().draft,'My question survives failure');assert.match(h.panel.innerHTML,/Key access denied/);
 const q=h.api.getPacket().questions.find(q=>q.role==='user');assert.equal(q.delivery,'failed');h.callbacks().onStatus({state:'disconnected'});h.setConnect(async()=>{});h.click('retry',q.id);await tick();assert.deepEqual(sent,['My question survives failure']);assert.equal(h.api.getPacket().questions.filter(q=>q.role==='user').length,1);
});
test('disconnect, context change and new evidence cancel queued sends without losing original drafts',async()=>{
 for(const action of ['disconnect','context','refresh']){
  const h=harness();await h.api.refresh();let release;h.setConnect(()=>new Promise(resolve=>release=resolve));const sent=[];h.setSend(async text=>sent.push(text));h.type('Must not reach a changed conversation');h.click('ask');await tick();
  if(action==='disconnect')h.click('disconnect');else if(action==='context'){h.ctx.timeframe='1h';h.api.contextChanged();}else{h.setCapture(async()=>snapshot('next'));await h.api.refresh();}
  release();await tick();assert.deepEqual(sent,[]);const p=action==='refresh'?h.api.getHistory()[0]:h.api.getPacket();assert.equal(p.draft,'Must not reach a changed conversation');assert.equal(p.questions.find(q=>q.role==='user').delivery,'failed');
 }
});
test('Save without sending works during a review while chat explains the temporary send restriction',async()=>{
 const h=harness();await h.api.refresh();const id=await reviewRequest(h);h.type('Keep this question for later');h.click('keep');assert.ok(h.api.getPacket().questions.some(q=>q.text==='Keep this question for later'&&q.delivery==='saved'));assert.match(h.panel.innerHTML,/Wait for it or choose Stop waiting/);
 const sent=[];h.setSend(async text=>sent.push(text));h.key();await tick();assert.deepEqual(sent,[]);h.callbacks().onMessage({role:'assistant',text:JSON.stringify({reviewId:id,...reviewFields})});h.key();await tick();assert.deepEqual(sent,['Keep this question for later']);
});
test('ordinary follow-up stays separate from headline review and follows its question before the composer',async()=>{
 const h=harness();await h.api.refresh();const id=await reviewRequest(h);h.callbacks().onMessage({role:'assistant',text:JSON.stringify({reviewId:id,...reviewFields})});h.type('Explain the concern in plain language');h.click('ask');await tick();h.callbacks().onMessage({role:'assistant',text:'A plain-language answer to the follow-up.'});
 assert.equal(h.api.getPacket().marketReview.reviewId,id);const chat=h.panel.innerHTML.slice(h.panel.innerHTML.indexOf('class="oa-transcript"'));assert.ok(chat.indexOf('Explain the concern in plain language')<chat.indexOf('A plain-language answer'));assert.ok(chat.indexOf('A plain-language answer')<chat.indexOf('class="oa-compose"'));assert.match(h.panel.innerHTML,/Shift\+Enter for a new line/);
});


test('unsent saved question is separate from the actual answered exchange and becomes latest when sent',async()=>{
 const h=harness();await h.api.refresh();h.type('QUESTION_A_SENT');h.click('ask');await tick();h.type('QUESTION_B_NOT_SENT');h.click('keep');h.callbacks().onMessage({role:'assistant',text:'REPLY_TO_A'});
 let chat=h.panel.innerHTML.split('aria-label="Discussion for this snapshot"')[1];let exchange=chat.split('aria-label="Questions not sent"')[0];assert.match(exchange,/QUESTION_A_SENT/);assert.match(exchange,/REPLY_TO_A/);assert.doesNotMatch(exchange,/QUESTION_B_NOT_SENT/);
 h.type('QUESTION_C_SENT');h.click('ask');await tick();h.callbacks().onMessage({role:'assistant',text:'REPLY_TO_C'});const b=h.api.getPacket().questions.find(q=>q.text==='QUESTION_B_NOT_SENT');h.click('retry',b.id);await tick();h.callbacks().onMessage({role:'assistant',text:'REPLY_TO_B'});chat=h.panel.innerHTML.split('aria-label="Discussion for this snapshot"')[1].split('Earlier messages')[0];assert.match(chat,/QUESTION_B_NOT_SENT/);assert.match(chat,/REPLY_TO_B/);assert.ok(chat.indexOf('QUESTION_C_SENT')<chat.indexOf('QUESTION_B_NOT_SENT'));assert.ok(chat.indexOf('QUESTION_B_NOT_SENT')<chat.indexOf('REPLY_TO_B'));
});
test('saving the question already connecting does not create a duplicate',async()=>{
 const h=harness();await h.api.refresh();let release;h.setConnect(()=>new Promise(r=>release=r));h.type('Same connecting question');h.click('ask');await tick();h.click('keep');assert.equal(h.api.getPacket().questions.filter(q=>q.role==='user').length,1);assert.match(h.panel.innerHTML,/already being sent/);release();await tick();assert.equal(h.api.getPacket().questions.filter(q=>q.role==='user').length,1);
});
test('cancelled older connection completion cannot add a session or replace a later connection error',async()=>{
 for(const rejectOld of [false,true]){
  const h=harness();await h.api.refresh();let finish,fail;h.setConnect(()=>new Promise((resolve,reject)=>{finish=resolve;fail=reject;}));h.click('connect-text');await tick();h.click('disconnect');await tick();h.setConnect(async()=>{});h.click('connect-text');await tick();assert.equal(h.api.getPacket().connectionCount,1);
  if(rejectOld)fail(Error('STALE_ERROR'));else finish();await tick();assert.equal(h.api.getPacket().connectionCount,1);assert.doesNotMatch(h.panel.innerHTML,/STALE_ERROR/);
 }
});

function localDiscussion(id){
 const s=snapshot(id);return{id:'read-'+id,snapshot:s,analysis:{timeframe:'15m'},draft:'Draft for '+id,connectionCount:3,marketReview:{reviewId:'review-'+id,...reviewFields,snapshotId:id,dataReference:s.dataReference,at:Date.now()},questions:[{id:'question-'+id,role:'user',text:'Question for '+id,delivery:'saved',snapshotId:id,dataReference:s.dataReference}]};
}
function localHistory(){return{version:2,active:localDiscussion('current'),history:[localDiscussion('old-a'),localDiscussion('old-b')],looseDraft:''};}
test('deleting an earlier discussion confirms scope and keeps the active discussion and other history',()=>{
 const h=harness(localHistory()),active=h.api.getPacket(),keep=h.api.getHistory()[1];h.click('delete-history','old-a');
 assert.equal(h.confirmations.length,1);assert.match(h.confirmations[0],/Saved Journal entries and ElevenLabs conversation records are not deleted/);assert.deepEqual(h.api.getPacket(),active);assert.deepEqual(h.api.getHistory(),[keep]);assert.equal(h.stored().history.length,1);assert.equal(h.journalSaves.length,0);
 const reloaded=harness(h.stored());assert.deepEqual(reloaded.api.getHistory().map(p=>p.snapshot.id),['old-b']);assert.equal(reloaded.api.getPacket().draft,active.draft);
});
test('clear earlier discussions requires confirmation and leaves current review, messages and draft',()=>{
 const h=harness(localHistory()),active=h.api.getPacket();h.setConfirmation(()=>false);h.click('delete-history','old-a');h.click('clear-history');assert.equal(h.api.getHistory().length,2);assert.equal(h.stored().history.length,2);
 h.setConfirmation(()=>true);h.click('clear-history');assert.deepEqual(h.api.getHistory(),[]);assert.deepEqual(h.stored().active,active);assert.deepEqual(h.api.getPacket(),active);assert.match(h.confirmations.at(-1),/Your current discussion will be kept/);assert.equal(h.journalSaves.length,0);
});
test('clear current messages preserves review, evidence, draft and history through reload',()=>{
 const h=harness(localHistory()),before=h.api.getPacket(),history=h.api.getHistory();h.setConfirmation(()=>false);h.click('clear-messages');assert.deepEqual(h.api.getPacket(),before);
 h.setConfirmation(()=>true);h.click('clear-messages');assert.deepEqual(h.api.getPacket(),{...before,questions:[]});assert.deepEqual(h.api.getHistory(),history);assert.match(h.confirmations.at(-1),/including questions saved without sending/);assert.equal(h.journalSaves.length,0);
 h.callbacks().onMessage({role:'assistant',text:'Late reply must not refill a cleared discussion'});assert.deepEqual(h.api.getPacket().questions,[]);
 const reloaded=harness(h.stored());assert.deepEqual(reloaded.api.getPacket(),{...before,questions:[]});
});
test('failed storage cannot claim successful removal or silently clear in-memory history or messages',()=>{
 for(const [action,id] of [['delete-history','old-a'],['clear-history'],['clear-messages']]){
  const h=harness(localHistory()),before=h.api.getPacket(),history=h.api.getHistory(),stored=h.stored();h.setStorageFailure(true);h.click(action,id);
  assert.deepEqual(h.api.getPacket(),before);assert.deepEqual(h.api.getHistory(),history);assert.deepEqual(h.stored(),stored);assert.match(h.panel.innerHTML,/could not save the removal/);assert.doesNotMatch(h.panel.innerHTML,/Messages cleared from|Saved discussion deleted from|Earlier discussions cleared from/);
 }
});
test('clear messages is blocked while connected, connecting or preparing evidence; histories cannot disappear during selection',async()=>{
 const h=harness(localHistory());h.click('connect-text');await tick();const connected=h.api.getPacket();h.click('clear-messages');assert.deepEqual(h.api.getPacket(),connected);assert.equal(h.confirmations.length,0);assert.match(h.panel.innerHTML,/End conversation before clearing messages/);
 h.click('disconnect');await tick();let finish;h.setConnect(()=>new Promise(resolve=>finish=resolve));h.click('connect-text');await tick();h.click('clear-messages');assert.equal(h.confirmations.length,0);h.click('disconnect');finish();await tick();h.callbacks().onStatus({state:'disconnected'});
 let capture;h.setCapture(()=>new Promise(resolve=>capture=resolve));const refreshing=h.api.refresh();await tick();h.click('clear-messages');h.click('clear-history');assert.equal(h.confirmations.length,0);capture(snapshot('next'));await refreshing;
 h.click('history','old-a');h.click('delete-history','old-a');h.click('clear-history');assert.equal(h.confirmations.length,0);await tick();assert.equal(h.api.getPacket().snapshot.id,'old-a');assert.ok(h.api.getHistory().some(p=>p.snapshot.id==='next'));
});
test('connected image-unavailable reason is visible beside controls and escaped',async()=>{
 const h=harness();await h.api.refresh();h.callbacks().onStatus({state:'connected',attachments:{available:false,reason:'Restart preview <script>unsafe</script>'}});
 assert.match(h.panel.innerHTML,/Chart image: Restart preview &lt;script&gt;unsafe&lt;\/script&gt;/);assert.doesNotMatch(h.panel.innerHTML,/<script>unsafe/);assert.match(h.panel.innerHTML,/Text, basic voice startup and image upload have been checked/);assert.match(h.panel.innerHTML,/Image interpretations can misread candles; compare them with the original chart/);
 h.callbacks().onStatus({state:'disconnected'});assert.doesNotMatch(h.panel.innerHTML,/Chart image: Restart preview/);
});

test('Discuss focuses the correct composer without sending, reconnecting or changing saved state',async()=>{
 for(const expanded of [false,true]){
  const h=harness(localHistory());await tick();h.type('Keep my unfinished question');
  let sent=0,focused=0,scrolled=0;
  h.setSend(async()=>sent++);
  const field={value:'Keep my unfinished question',selectionStart:5,selectionEnd:9,focus(){focused++;},scrollIntoView(){scrolled++;}};
  const other={focus(){assert.fail('The other view must not receive focus');}};
  h.panel.querySelector=()=>expanded?other:field;h.dialog.querySelector=()=>expanded?field:other;
  const before=h.api.getPacket(),history=h.api.getHistory(),stored=h.stored(),disconnects=h.disconnects();
  const container=expanded?h.dialog:h.panel;
  container.events.click({target:{closest:()=>({dataset:{oa:'discuss'},closest:()=>container})}});
  await tick();
  assert.equal(focused,1);assert.equal(scrolled,1);assert.equal(sent,0);assert.equal(h.disconnects(),disconnects);
  assert.equal(field.selectionStart,5);assert.equal(field.selectionEnd,9);
  assert.deepEqual(h.api.getPacket(),before);assert.deepEqual(h.api.getHistory(),history);assert.deepEqual(h.stored(),stored);
 }
});
test('saved reading leads with evidence, qualification and explicit snapshot context',async()=>{
 const h=harness(localHistory());await tick();h.ctx.symbol='frxEURUSD';h.ctx.label='EUR/USD';h.api.contextChanged();
 const html=h.panel.innerHTML;
 const ordered=['class="oa-context"','Snapshot cutoff','class="oa-review-reading"','<h3>Why</h3>','<h3>Watch</h3>','<h3>Invalidated if</h3>','data-oa="discuss"','The chart is now EUR/USD','aria-label="Discuss this reading"','data-oa-section="more"','Request another review','<summary>Review limits</summary>','Market facts','<footer class="oa-compose"'];
 ordered.forEach((text,i)=>{assert.ok(html.includes(text),text);if(i)assert.ok(html.indexOf(ordered[i-1])<html.indexOf(text),text);});
 assert.match(html,/Saved evidence · stays fixed during discussion/);assert.match(html,/saved review and recent sent messages into the new session/);
 assert.doesNotMatch(html,/Oracle agrees|confidence|data-oa="review"[^>]*class="oa-primary"/);
 assert.match(html,/<button class="oa-secondary" data-oa="review" disabled/);
});
test('request another review waits for an image upload instead of disconnecting it',async()=>{
 const h=harness(localHistory());await tick();h.click('connect-text');await tick();
 let finish,uploads=0;h.setAttachment(()=>{uploads++;return new Promise(resolve=>finish=resolve);});
 h.panel.events.change({target:{files:[{name:'chart.png'}],matches:()=>true,closest:()=>h.panel}});
 await tick();assert.equal(uploads,1);
 const before=h.disconnects(),packet=h.api.getPacket();h.click('review');await tick();
 assert.equal(h.disconnects(),before);assert.deepEqual(h.api.getPacket(),packet);
 assert.match(h.panel.innerHTML,/<button class="oa-secondary" data-oa="review" disabled/);
 assert.match(h.panel.innerHTML,/Wait for the chart image to finish uploading/);
 finish({snapshotId:packet.snapshot.id,name:'chart.png',type:'image/png',size:20});await tick();h.callbacks().onMessage({role:'assistant',text:'Image reply arrived'});
 assert.match(h.panel.innerHTML,/<button class="oa-secondary" data-oa="review" >/);
});

function intradaySnapshot(id='intraday-a'){
 const s=snapshot(id);s.profile='intraday-v1';s.series=Object.fromEntries(Object.entries({'4h':14400,'1h':3600,'15m':900,'5m':300}).map(([tf,sec])=>{const end=Math.floor(asOf/sec)*sec;return[tf,{status:'ready',source:'Deriv',capturedAt:asOf+1,candles:Array.from({length:80},(_,i)=>({time:end-(80-i)*sec,open:100+i,high:102+i,low:99+i,close:101+i}))}];}));return s;
}
function directionalIntraday(kinds=['up','up','up','up']){
 const s=intradaySnapshot('automatic-hierarchy');
 for(const [index,tf] of ['4h','1h','15m','5m'].entries())s.series[tf].candles.forEach((bar,i)=>{
  const center=200+(kinds[index]==='down'?-1:1)*Math.floor(i/5)*2+[0,4,2,-4,-2][i%5];
  Object.assign(bar,{open:center,close:center,high:center+.5,low:center-.5});
 });return s;
}
test('automatic interpretation leads both views immediately without a connection, and survives reload and Journal handoff',async()=>{
 const h=harness(),s=directionalIntraday();let sends=0;h.setSend(async()=>sends++);h.setCapture(async()=>s);await h.api.refresh();
 assert.equal(h.connections.length,0);assert.equal(sends,0);assert.equal(h.api.getPacket().marketReview,undefined);
 const reading=h.api.getPacket().analysis.interpretation;assert.equal(reading.relationship,'aligned');h.api.open();
 for(const html of [h.panel.innerHTML,h.dialog.innerHTML]){
  assert.match(html,/Automatic structure read · completed candles/);assert.match(html,/Bullish across 4H, 1H, 15m and 5m/);
  assert.ok(html.indexOf(reading.reading)<html.indexOf('How the timeframes fit'));
  assert.doesNotMatch(html,/Awaiting interpretation|Get Oracle’s view of this market/);
  for(const tf of ['4h','1h','15m','5m'])assert.match(html,new RegExp('aria-label="'+tf.toUpperCase()+' [^"]+: Bullish\\.'));
 }
 h.click('journal');assert.equal(h.journalSaves[0].marketReview,undefined);assert.deepEqual(h.journalSaves[0].analysis.interpretation,reading);
 const saved=h.stored();saved.active.analysis.interpretation.reading='FORGED_CACHED_INTERPRETATION';saved.active.analysis.interpretation.relationship='conflicting';
 const loaded=harness(saved);await tick();assert.deepEqual(loaded.api.getPacket().analysis.interpretation,reading);assert.doesNotMatch(loaded.panel.innerHTML,/FORGED_CACHED_INTERPRETATION/);assert.equal(loaded.connections.length,0);
});
test('automatic conflict stays explicit and a separately requested agent review retains precedence',async()=>{
 const h=harness();h.setCapture(async()=>directionalIntraday(['up','down','up','up']));await h.api.refresh();
 assert.equal(h.api.getPacket().analysis.interpretation.relationship,'conflicting');assert.match(h.panel.innerHTML,/Bullish 4H context conflicts with bearish 1H structure/);
 const id=await reviewRequest(h);h.callbacks().onMessage({role:'assistant',text:JSON.stringify({reviewId:id,...reviewFields,mtf:mtfReview})});
 assert.match(h.panel.innerHTML,/Connected agent interpretation/);assert.ok(h.panel.innerHTML.indexOf(reviewFields.reading)<h.panel.innerHTML.indexOf('How the timeframes fit'));
 assert.match(h.panel.innerHTML,/Mixed \/ partial/);assert.equal(h.api.getPacket().analysis.interpretation.relationship,'conflicting');
 assert.equal(h.callbacks().getDiscussionContext().review.reading,reviewFields.reading);assert.equal(h.callbacks().getEvidence().source,undefined);
 assert.equal(h.callbacks().getEvidence().interpretation,undefined,'Derived interpretation is not silently sent as independent raw market evidence');h.click('disconnect');
});
test('a completed new capture shows its conclusion at the top while a failed capture preserves the current reading and scroll',async()=>{
 const h=harness();h.setCapture(async()=>directionalIntraday());await h.api.refresh();const dom=renderedDom(h);h.api.open();
 for(const expanded of [false,true])dom.node('[data-oa-scroll]',expanded).scrollTop=380;
 h.setCapture(async()=>{throw Error('New history temporarily unavailable');});await h.api.refresh();
 for(const expanded of [false,true])assert.equal(dom.node('[data-oa-scroll]',expanded).scrollTop,380);
 const original=h.api.getPacket();h.setCapture(async()=>({...directionalIntraday(),id:'new-completed-capture'}));await h.api.refresh();
 for(const expanded of [false,true])assert.equal(dom.node('[data-oa-scroll]',expanded).scrollTop,0);
 assert.equal(h.api.getPacket().snapshot.id,'new-completed-capture');assert.ok(h.api.getHistory().some(p=>p.snapshot.id===original.snapshot.id));assert.equal(h.connections.length,0);
});
const mtfReview={profile:'intraday-v1',relationship:'mixed',governing:'4h supplies context; 15m defines the setup and 5m its timing.',setupCondition:'No defined trigger; the supplied sample has no confirmed swing pairs.',setupInvalidation:'No specific setup invalidation is justified by these facts.',contextInvalidation:'Higher context needs a new completed 4h structure assessment.',frames:['4h','1h','15m','5m'].map(tf=>({timeframe:tf,reading:'Structure is undetermined in this sample.',evidence:'The completed closes rose, but no confirmed pivot pairs exist.'}))};
test('intraday capture requests four-frame profile; review requires hierarchy and preserves it across reload, discussion and Journal',async()=>{
 const h=harness();let options;h.setCapture(async(_h,o)=>{options=o;return intradaySnapshot();});await h.api.refresh();assert.equal(options.profile,'intraday-v1');assert.equal(h.api.getPacket().analysis.status,'Data available');assert.equal(h.api.getPacket().analysis.profile,'intraday-v1');
 let prompt;h.setSend(async text=>prompt=text);h.click('review');await tick();const schema=JSON.parse(prompt.slice(prompt.indexOf('{')));assert.deepEqual(schema.mtf.frames.map(f=>f.timeframe),['4h','1h','15m','5m']);assert.match(prompt,/not an automatic veto/);assert.match(prompt,/Do not vote or average/);
 h.callbacks().onMessage({role:'assistant',text:JSON.stringify({reviewId:schema.reviewId,...reviewFields})});assert.equal(h.api.getPacket().marketReview,undefined);assert.match(h.panel.innerHTML,/incomplete timeframe review/);
 const id=await reviewRequest(h);h.callbacks().onMessage({role:'assistant',text:JSON.stringify({reviewId:id,...reviewFields,mtf:mtfReview})});assert.deepEqual(h.api.getPacket().marketReview.mtf,mtfReview);assert.ok(h.panel.innerHTML.indexOf(reviewFields.reading)<h.panel.innerHTML.indexOf('How the timeframes fit'));assert.match(h.panel.innerHTML,/<h3>Invalidated if<\/h3>/);assert.match(h.panel.innerHTML,/<h4>Setup<\/h4>/);assert.match(h.panel.innerHTML,/<h4>Higher context<\/h4>/);assert.doesNotMatch(h.panel.innerHTML,/\+ null/);assert.deepEqual(h.callbacks().getDiscussionContext().review.mtf,mtfReview);
 h.click('journal');assert.deepEqual(h.journalSaves[0].marketReview.mtf,mtfReview);const saved=h.stored();h.click('disconnect');const loaded=harness(saved);assert.deepEqual(loaded.api.getPacket().marketReview.mtf,mtfReview);
});
test('intraday missing history keeps three frames visible and blocks a full review without preventing questions',async()=>{
 const h=harness(),s=intradaySnapshot();delete s.series['4h'];h.setCapture(async()=>s);await h.api.refresh();assert.equal(h.api.getPacket().analysis.status,'Insufficient information');assert.equal(Object.keys(h.api.getPacket().analysis.metrics).length,3);assert.match(h.panel.innerHTML,/Incomplete evidence/);assert.match(h.panel.innerHTML,/All four completed timeframe histories/);h.click('review');await tick();assert.equal(h.connections.length,0);h.type('What evidence is missing?');h.click('ask');await tick();assert.equal(h.connections.length,1);h.click('disconnect');
});
test('intraday chart anchor outside the profile never substitutes or invents an extra frame',async()=>{
 const h=harness();h.ctx.timeframe='1m';h.setCapture(async()=>intradaySnapshot());await h.api.refresh();assert.equal(h.api.getPacket().analysis.status,'Data available');assert.deepEqual(Object.keys(h.api.getPacket().analysis.metrics),['4h','1h','15m','5m']);assert.match(h.panel.innerHTML,/Four-timeframe evidence/);assert.doesNotMatch(h.panel.innerHTML,/\+ null/);
});
test('saved intraday review rejects duplicate frames and strips unknown model fields',async()=>{
 const h=harness();h.setCapture(async()=>intradaySnapshot());await h.api.refresh();const id=await reviewRequest(h);h.callbacks().onMessage({role:'assistant',text:JSON.stringify({reviewId:id,...reviewFields,mtf:{...mtfReview,secret:'NOT_RETAINED',frames:mtfReview.frames.map(f=>({...f,secret:'NOT_RETAINED'}))}})});const saved=h.stored();assert.doesNotMatch(JSON.stringify(saved.active.marketReview),/NOT_RETAINED/);h.click('disconnect');saved.active.marketReview.mtf.frames[3]=saved.active.marketReview.mtf.frames[0];const loaded=harness(saved);assert.equal(loaded.api.getPacket().marketReview,null);
});

test('account clear and reload never write or carry old draft, messages or callbacks into another account',async()=>{
 const h=harness();await h.api.refresh();h.type('Account A private draft');h.click('connect-text');await tick();const previous=h.callbacks(),storedA=h.stored(),writes=h.writes();
 h.api.clearForAccountChange();assert.equal(h.api.getPacket(),null);assert.deepEqual(h.api.getHistory(),[]);assert.deepEqual(h.stored(),storedA);assert.equal(h.writes(),writes);
 previous.onMessage({role:'assistant',text:'Late account A answer'});previous.onError('Late private error');previous.onStatus({state:'connected',mode:'voice'});assert.equal(h.writes(),writes);assert.doesNotMatch(h.panel.innerHTML,/Late private error|microphone active/);
 const savedB=localHistory();savedB.active.draft='Account B draft';h.setSaved(savedB);h.api.reloadStorage();await tick();assert.equal(h.api.getPacket().draft,'Account B draft');assert.equal(h.writes(),writes);assert.doesNotMatch(JSON.stringify(h.api.getPacket()),/Account A private draft|Late account A/);assert.throws(()=>previous.getEvidence(),/account changed/);
});
test('an old account pending send cannot persist after the next account reloads',async()=>{
 const h=harness();await h.api.refresh();let finish;h.setSend(()=>new Promise(r=>finish=r));h.type('Account A pending send');h.click('ask');await tick();assert.ok(finish);h.api.clearForAccountChange();const savedB=localHistory();savedB.active.draft='Account B retained';h.setSaved(savedB);h.api.reloadStorage();await tick();const writes=h.writes(),before=h.stored();finish();await tick();assert.equal(h.writes(),writes);assert.deepEqual(h.stored(),before);assert.equal(h.api.getPacket().draft,'Account B retained');
});
test('an old account pending capture cannot replace the next account snapshot or write storage',async()=>{
 const h=harness();let finish;h.setCapture(()=>new Promise(r=>finish=r));const pending=h.api.refresh();await tick();h.api.clearForAccountChange();const savedB=localHistory();h.setSaved(savedB);h.api.reloadStorage();await tick();const writes=h.writes(),before=h.api.getPacket();finish(snapshot('late-account-a'));await pending;assert.deepEqual(h.api.getPacket(),before);assert.equal(h.writes(),writes);
});
test('signed-in storage status is escaped and guest fallback stays unchanged',async()=>{
 const h=harness();await tick();assert.match(h.panel.innerHTML,/stay in this browser/);global.ProTraderStorageStatus=()=>'<Account status>';h.api.render();assert.match(h.panel.innerHTML,/&lt;Account status&gt;/);delete global.ProTraderStorageStatus;
});
test('old account image completion cannot write into newly loaded account data',async()=>{
 const h=harness();await h.api.refresh();h.click('connect-text');await tick();let finish;h.setAttachment(()=>new Promise(r=>finish=r));h.type('Account A image question');h.panel.events.change({target:{files:[{name:'a.png',type:'image/png',size:20}],matches:()=>true,closest:()=>h.panel}});await tick();assert.ok(finish);h.api.clearForAccountChange();h.setSaved(localHistory());h.api.reloadStorage();await tick();const writes=h.writes(),before=h.stored();finish({snapshotId:'snapshot-a',name:'a.png',type:'image/png',size:20});await tick();assert.equal(h.writes(),writes);assert.deepEqual(h.stored(),before);assert.doesNotMatch(JSON.stringify(h.api.getPacket()),/Account A image question/);
});
test('old account review send completion cannot persist after an account swap',async()=>{
 const h=harness(localHistory());await tick();let finish;h.setSend(()=>new Promise(r=>finish=r));h.click('review');await tick();assert.ok(finish);h.api.clearForAccountChange();const next=localHistory();next.active.draft='New account review context';h.setSaved(next);h.api.reloadStorage();await tick();const writes=h.writes(),before=h.stored();finish();await tick();assert.equal(h.writes(),writes);assert.deepEqual(h.stored(),before);assert.equal(h.api.getPacket().draft,'New account review context');
});

// Recreate the small rendered DOM surface needed for layout interaction tests.
// Unlike the legacy transport harness, this discards nodes on each paint so a
// test cannot pass by retaining focus, disclosure or scroll on an old element.
function renderedDom(h){
 const decode=s=>String(s).replace(/&lt;/g,'<').replace(/&gt;/g,'>').replace(/&quot;/g,'"').replace(/&#39;/g,"'").replace(/&amp;/g,'&');
 function install(container){
  let html=container.innerHTML,nodes=[];
  const matches=(node,selector)=>{
   if(selector.includes(','))return selector.split(',').some(s=>matches(node,s.trim()));
   const tag=/^[a-z]+/i.exec(selector)?.[0];if(tag&&node.tagName!==tag.toUpperCase())return false;
   for(const name of selector.matchAll(/\.([a-z][\w-]*)/gi))if(!(node.attrs.class||'').split(/\s+/).includes(name[1]))return false;
   for(const m of selector.matchAll(/\[([\w-]+)(?:=["']?([^\]"']+)["']?)?\]/g)){
    if(m[1]==='open'){if(!node.open)return false;}else if(!(m[1]in node.attrs)||m[2]!==undefined&&node.attrs[m[1]]!==m[2])return false;
   }
   return true;
  };
  const parse=()=>{
   nodes=[];
   for(const match of html.matchAll(/<(button|textarea|details|div|footer|input)\b([^>]*)>/g)){
    const attrs={};for(const a of match[2].matchAll(/([\w-]+)(?:="([^"]*)")?/g))attrs[a[1]]=decode(a[2]??'');
    const dataset=Object.fromEntries(Object.entries(attrs).filter(([k])=>k.startsWith('data-')).map(([k,v])=>[k.slice(5).replace(/-([a-z])/g,(_,c)=>c.toUpperCase()),v]));
    const node={tagName:match[1].toUpperCase(),attrs,dataset,id:attrs.id,open:'open'in attrs,hidden:'hidden'in attrs,disabled:'disabled'in attrs,scrollTop:0,scrollHeight:0,clientHeight:0,selectionStart:0,selectionEnd:0,
     matches(selector){return matches(this,selector);},focus(){h.doc.activeElement=this;},setSelectionRange(start,end){this.selectionStart=start;this.selectionEnd=end;},scrollIntoView(){this.scrolled=true;},
     getAttribute(name){return this.attrs[name]??null;},setAttribute(name,value){this.attrs[name]=String(value);},
     closest(selector){return selector==='[data-oa]'?('oa'in this.dataset?this:null):container;}};
    if(match[1]==='textarea')node.value=decode(html.slice(match.index+match[0].length).split('</textarea>')[0]);
    nodes.push(node);
   }
  };
  Object.defineProperty(container,'innerHTML',{get:()=>html,set:value=>{html=value;parse();},configurable:true});parse();
  container.querySelector=selector=>nodes.find(n=>matches(n,selector))||null;
  container.querySelectorAll=selector=>nodes.filter(n=>matches(n,selector));
  return{id:id=>nodes.find(n=>n.id===id),nodes:()=>nodes};
 }
 const panel=install(h.panel),dialog=install(h.dialog);
 h.doc.activeElement=null;h.doc.getElementById=id=>id==='oracle-panel'?h.panel:id==='oracleAnalystDialog'?h.dialog:panel.id(id)||dialog.id(id)||null;
 h.doc.querySelector=selector=>h.panel.querySelector(selector)||h.dialog.querySelector(selector);
 const container=expanded=>expanded?h.dialog:h.panel;
 return{
  input:expanded=>container(expanded).querySelector('[data-oa-question]'),
  section:(key,expanded=false)=>container(expanded).querySelector(`details[data-oa-section="${key}"]`),
  node:(selector,expanded=false)=>container(expanded).querySelector(selector),
  type(text,expanded=false){const input=this.input(expanded);input.value=text;container(expanded).events.input({target:input});},
  click(action,extra={},expanded=false){const button=container(expanded).querySelectorAll('[data-oa]').find(n=>n.dataset.oa===action&&Object.entries(extra).every(([k,v])=>n.dataset[k]===v));assert.ok(button,`Missing ${action} control`);assert.equal(button.disabled,false,`${action} should be available`);button.focus();container(expanded).events.click({target:button});},
  key(options={},expanded=false){const event={target:this.input(expanded),key:'Enter',preventDefault(){this.prevented=true;},stopPropagation(){},...options};container(expanded).events.keydown(event);return event;},
 };
}

function savedIntradayLayout(){
 const s=intradaySnapshot('layout-intraday'),active=localDiscussion('layout-intraday');
 active.snapshot=s;active.marketReview={...active.marketReview,dataReference:s.dataReference,mtf:mtfReview};
 return{version:2,active,history:[],looseDraft:''};
}
test('compact layout keeps secondary actions under More and primary question controls after the reader',async()=>{
 const h=harness(localHistory());await tick();const html=h.panel.innerHTML;
 const more=html.indexOf('data-oa-section="more"'),composer=html.indexOf('<footer class="oa-compose"');
 assert.ok(html.includes('data-oa-scroll'));assert.ok(more>0);assert.ok(composer>more);assert.match(html,/<summary>More options<\/summary>/);
 for(const action of ['keep','idea','journal','plan']){const at=html.indexOf(`data-oa="${action}"`);assert.ok(at>more&&at<composer,action+' belongs in More');}
 for(const action of ['ask','connect-voice','image'])assert.ok(html.indexOf(`data-oa="${action}"`)>composer,action+' stays by the question');
 assert.ok(html.indexOf(reviewFields.reading)<html.indexOf('aria-label="Discuss this reading"'));
});
test('timeframe chips reveal one linked evidence detail without sending, and keep the focused view',async()=>{
 const h=harness(savedIntradayLayout());await tick();const dom=renderedDom(h);h.api.open();
 const before=h.api.getPacket(),connections=h.connections.length;
 for(const expanded of [false,true]){
  for(const tf of ['4h','1h','15m','5m']){
   const chip=dom.node(`[data-oa="frame"][data-timeframe="${tf}"]`,expanded);assert.ok(chip);assert.equal(chip.tagName,'BUTTON');
   const target=h.doc.getElementById(chip.getAttribute('aria-controls'));assert.ok(target,'Each chip has its own linked detail');assert.equal(target.dataset.oaFrame,tf);
  }
  dom.click('frame',{timeframe:'4h'},expanded);
  let chip=dom.node('[data-oa="frame"][data-timeframe="4h"]',expanded);assert.equal(chip.getAttribute('aria-expanded'),'true');assert.equal(h.doc.activeElement,chip);
  assert.equal(h.doc.getElementById(chip.getAttribute('aria-controls')).hidden,false);
  dom.click('frame',{timeframe:'5m'},expanded);
  assert.equal(dom.node('[data-oa="frame"][data-timeframe="4h"]',expanded).getAttribute('aria-expanded'),'false');
  chip=dom.node('[data-oa="frame"][data-timeframe="5m"]',expanded);assert.equal(chip.getAttribute('aria-expanded'),'true');assert.equal(h.doc.activeElement,chip);
  dom.click('frame',{timeframe:'5m'},expanded);assert.equal(dom.node('[data-oa="frame"][data-timeframe="5m"]',expanded).getAttribute('aria-expanded'),'false');
 }
 assert.equal(h.connections.length,connections);assert.deepEqual(h.api.getPacket(),before);
});
test('reply redraw preserves More, reader scroll and the current composer selection in both views',async()=>{
 for(const expanded of [false,true]){
  const h=harness(localHistory());await tick();const dom=renderedDom(h);if(expanded)h.api.open();
  dom.section('more',expanded).open=true;dom.node('[data-oa-scroll]',expanded).scrollTop=240;
  dom.type('A private draft kept while the reading updates',expanded);const input=dom.input(expanded);input.focus();input.setSelectionRange(10,18);
  h.callbacks().onStatus({state:'disconnected',reason:'Status refreshed'});
  assert.notEqual(dom.input(expanded),input,'A new DOM input should replace the previous node');assert.equal(h.doc.activeElement,dom.input(expanded));
  assert.equal(dom.input(expanded).selectionStart,10);assert.equal(dom.input(expanded).selectionEnd,18);
  assert.equal(dom.node('[data-oa-scroll]',expanded).scrollTop,240);assert.equal(dom.section('more',expanded).open,true);
  assert.equal(dom.input(expanded).value,'A private draft kept while the reading updates');assert.equal(h.api.getPacket().draft,dom.input(expanded).value);
 }
});
test('the persistent composer keeps Enter send and Shift+Enter newline in each rendered view',async()=>{
 for(const expanded of [false,true]){
  const h=harness(localHistory());await tick();const dom=renderedDom(h);if(expanded)h.api.open();const sent=[];h.setSend(async text=>sent.push(text));
  dom.type('Question from '+(expanded?'expanded view':'panel'),expanded);dom.input(expanded).focus();
  assert.equal(dom.key({shiftKey:true},expanded).prevented,undefined);assert.equal(dom.key({isComposing:true},expanded).prevented,undefined);dom.key({repeat:true},expanded);await tick();assert.deepEqual(sent,[]);
  assert.equal(dom.key({},expanded).prevented,true);dom.key({},expanded);await tick();assert.deepEqual(sent,['Question from '+(expanded?'expanded view':'panel')]);
  h.callbacks().onMessage({role:'assistant',text:'One answer to this question'});h.click('disconnect');
 }
});
test('panel and expanded composers retain distinct labels, context and live send instructions',async()=>{
 const h=harness(savedIntradayLayout());await tick();const dom=renderedDom(h);h.api.open();
 for(const expanded of [false,true]){
  const suffix=expanded?'Dialog':'Panel',html=(expanded?h.dialog:h.panel).innerHTML,input=dom.input(expanded);
  assert.equal(input.id,'oaQuestion'+suffix);assert.match(html,new RegExp('<label[^>]*for="oaQuestion'+suffix+'"'));
  assert.equal(input.attrs.enterkeyhint,'send');assert.match(input.attrs['aria-describedby'],new RegExp('oaSendHint'+suffix));assert.match(input.attrs['aria-describedby'],new RegExp('oaSendState'+suffix));
  for(const id of input.attrs['aria-describedby'].split(/\s+/))assert.match(html,new RegExp('id="'+id+'"'));
  assert.match(html,/aria-label="Discuss this reading"/);assert.match(html,/Vol 50/);assert.match(html,/4h/);assert.match(html,/5m/);assert.match(html,/Saved evidence · stays fixed during discussion/);
 }
 const ids=[...h.panel.innerHTML.matchAll(/\sid="([^"]+)"/g),...h.dialog.innerHTML.matchAll(/\sid="([^"]+)"/g)].map(m=>m[1]);assert.equal(ids.length,new Set(ids).size,'Panel and expanded view must not duplicate IDs');
});
test('secondary draft and Journal actions still delegate correctly from More without sending',async()=>{
 const h=harness(localHistory());await tick();const dom=renderedDom(h);dom.section('more').open=true;let sent=0;h.setSend(async()=>sent++);
 dom.type('');dom.click('idea');assert.equal(h.api.getPacket().draft,'My idea is: ');dom.type('Keep this hypothesis unsent');dom.click('keep');
 assert.ok(h.api.getPacket().questions.some(q=>q.text==='Keep this hypothesis unsent'&&q.delivery==='saved'));
 dom.click('journal');assert.equal(h.journalSaves.length,1);assert.equal(h.journalSaves[0].snapshot.id,'current');assert.equal(sent,0);assert.equal(h.connections.length,0);
});
test('compact timeframe chips keep missing evidence explicit and cannot turn it into a direction',async()=>{
 const h=harness(),s=intradaySnapshot();delete s.series['4h'];h.setCapture(async()=>s);await h.api.refresh();
 const html=h.panel.innerHTML,chip=html.match(/<button\b[^>]*data-timeframe="4h"[^>]*>([\s\S]*?)<\/button>/)?.[1];
 assert.ok(chip,'Missing 4h still has a discoverable chip');assert.match(chip,/Unavailable|Missing|No verified/i);assert.doesNotMatch(chip,/Bullish|Bearish|Aligned/i);
 const dom=renderedDom(h);dom.click('frame',{timeframe:'4h'});const current=dom.node('[data-oa="frame"][data-timeframe="4h"]');assert.equal(current.getAttribute('aria-expanded'),'true');assert.equal(h.doc.getElementById(current.getAttribute('aria-controls')).hidden,false);
 assert.equal(h.api.getPacket().analysis.status,'Insufficient information');assert.equal(h.connections.length,0);
});

test('compact chips show only explicit normalized agent bias, preserved across reload and Journal',async()=>{
 const saved=structuredClone(savedIntradayLayout()),biases=['bullish','bearish','mixed','undetermined'];
 saved.active.marketReview.mtf.frames.forEach((frame,i)=>frame.bias=biases[i]);
 const h=harness(saved);await tick();const dom=renderedDom(h),labels=['Bullish','Bearish','Mixed','Unclear'];
 for(const [index,tf] of ['4h','1h','15m','5m'].entries()){
  const chip=dom.node(`[data-oa="frame"][data-timeframe="${tf}"]`);assert.ok(chip.getAttribute('aria-label').includes(labels[index]));
  assert.equal(h.api.getPacket().marketReview.mtf.frames[index].bias,biases[index]);
 }
 h.click('journal');assert.deepEqual(h.journalSaves[0].marketReview.mtf.frames.map(f=>f.bias),biases);
 const loaded=harness(h.stored());await tick();assert.deepEqual(loaded.api.getPacket().marketReview.mtf.frames.map(f=>f.bias),biases);
});
test('legacy or invalid frame bias falls back to labelled observations without mining prose for direction',async()=>{
 for(const bias of [undefined,'guaranteed bullish']){
  const saved=structuredClone(savedIntradayLayout());saved.active.marketReview.mtf.frames[0].reading='Bullish outlook claimed in this saved prose.';
  if(bias!==undefined)saved.active.marketReview.mtf.frames[0].bias=bias;
  const h=harness(saved);await tick();const dom=renderedDom(h),chip=dom.node('[data-oa="frame"][data-timeframe="4h"]');
  assert.match(chip.getAttribute('aria-label'),/Unclear swings/);assert.doesNotMatch(chip.getAttribute('aria-label'),/Bullish|guaranteed/);
  assert.equal(h.api.getPacket().marketReview.mtf.frames[0].bias,undefined);
  dom.click('frame',{timeframe:'4h'});assert.match(h.panel.innerHTML,/Chip describes calculated swing structure; it is not an agent direction rating/);
  assert.match(h.panel.innerHTML,/Bullish outlook claimed in this saved prose/,'Saved interpretation still appears in its evidence detail');
 }
});
test('a completed review leads both readers while review messages stay in More and ordinary discussion remains visible',async()=>{
 const h=harness(savedIntradayLayout());await tick();const dom=renderedDom(h);h.api.open();
 dom.type('Keep this next question private',true);const id=await reviewRequest(h);
 for(const expanded of [false,true])dom.node('[data-oa-scroll]',expanded).scrollTop=360;
 dom.input(true).focus();dom.input(true).setSelectionRange(5,10);
 const reading='New complete review based on the saved hierarchy.';
 h.callbacks().onMessage({role:'assistant',text:JSON.stringify({reviewId:id,...reviewFields,reading,mtf:mtfReview})});
 for(const expanded of [false,true]){
  const html=(expanded?h.dialog:h.panel).innerHTML,more=html.indexOf('data-oa-section="more"'),reviewMessages=html.indexOf('data-oa-section="review-messages"');
  assert.ok(html.indexOf(reading)<more);assert.ok(reviewMessages>more);assert.ok(html.indexOf('Review the 4H, 1H, 15m and 5m hierarchy:')>reviewMessages);
  assert.equal(dom.section('review-messages',expanded).open,false);assert.equal(dom.node('[data-oa-scroll]',expanded).scrollTop,0);
 }
 assert.equal(h.doc.activeElement,dom.input(true));assert.equal(dom.input(true).selectionStart,5);assert.equal(dom.input(true).selectionEnd,10);assert.equal(h.api.getPacket().draft,'Keep this next question private');
 dom.type('How should I read the conflict?',true);dom.click('ask',{},true);await tick();
 for(const expanded of [false,true])dom.node('[data-oa-scroll]',expanded).scrollTop=180;
 h.callbacks().onMessage({role:'assistant',text:'Compare the lower setup with the higher context.'});
 for(const expanded of [false,true]){
  const html=(expanded?h.dialog:h.panel).innerHTML;assert.ok(html.indexOf('Compare the lower setup')<html.indexOf('data-oa-section="more"'));assert.equal(dom.node('[data-oa-scroll]',expanded).scrollTop,180);
 }
 h.click('disconnect');
});
