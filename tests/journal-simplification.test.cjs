const {test}=require('node:test');
const assert=require('node:assert/strict');
const Workspace=require('../static/oracle-workspace.js');
const clone=value=>JSON.parse(JSON.stringify(value));
const decode=value=>value.replace(/&lt;/g,'<').replace(/&gt;/g,'>').replace(/&quot;/g,'"').replace(/&#39;/g,"'").replace(/&amp;/g,'&');

function mounted({saved=null,trades=[]}={}){
 let raw=saved?JSON.stringify(saved):null,fail=false,writes=0,html='';
 const elements={owSave:{textContent:'',classList:{toggle(){}}},owNoteStatus:{textContent:''},owTitle:{focus(){}},'ow-trade-reflection':{value:''}};
 const storage={getItem(){return raw;},setItem(_key,value){writes++;if(fail)throw Error('Storage full');raw=value;}};
 global.localStorage=storage;
 const dialog={open:false,events:{},scrollTop:0,setAttribute(){},addEventListener(k,f){this.events[k]=f;},showModal(){this.open=true;},close(){this.open=false;},get innerHTML(){return html;},set innerHTML(value){html=value;const field=value.match(/<textarea id="ow-trade-reflection"[^>]*>([\s\S]*?)<\/textarea>/);elements['ow-trade-reflection'].value=field?decode(field[1]):'';}};
 const doc={body:{appendChild(){}},createElement:()=>dialog,getElementById:key=>elements[key]||null};
 delete require.cache[require.resolve('../static/oracle-workspace.js')];
 const api=require('../static/oracle-workspace.js');
 api.mount(doc,{getContext:()=>({symbol:'FIXTURE',label:'Fictional fixture',timeframe:'15m'}),getTrades:()=>trades});
 return{api,dialog,elements,trades,stored:()=>raw?JSON.parse(raw):null,raw:()=>raw,writes:()=>writes,failStorage(value=true){fail=value;},
  click(action,extra={}){dialog.events.click({target:{closest:()=>({dataset:{action,...extra}})}});},
  typeNote(value){elements['ow-trade-reflection'].value=value;dialog.events.input({target:{dataset:{tradeNote:''},value}});},
  type(field,value){dialog.events.input({target:{dataset:{field},value,type:'textarea'}});}
 };
}

function trade(overrides={}){return{id:'ticket-1',sym:'FIXTURE',pair:'TEST/USD',type:'buy',volume:0.1,entry:100,exit:104,pnl:4,openTime:1728000000000,closeTime:1728000900000,reason:'Manual',...overrides};}
function analysisPacket(){
 const snapshot={version:1,id:'frozen-evidence',symbol:'OTHER',label:'Other fictional market',asOf:1000,capturedAt:1000,dataReference:'supplied-facts',series:{}};
 return{id:'saved-reading',snapshot,analysis:{timeframe:'15m',summary:'A retained calculated summary.'},questions:[{question:'What would change this?',response:'A completed close through the observed boundary.'}],marketReview:{reviewId:'review-1',at:1728000900000,snapshotId:snapshot.id,dataReference:snapshot.dataReference,reading:'The captured market remains inside its observed range.',support:'The completed bars provide a visible reference.',concern:'No later continuation has been confirmed.',whatChanges:'A completed close through the boundary would change the reading.',limits:'No news or order-flow evidence was supplied.'}};
}
function record(){
 const hypothesis=Workspace.makeHypothesis({symbol:'FIXTURE',timeframe:'15m'});
 const snapshot={version:1,id:'plan-evidence',symbol:'FIXTURE',asOf:1000,series:{}};
 return Workspace.createRecord({hypothesis,snapshot,review:{snapshotId:snapshot.id,hypothesisId:hypothesis.id,assessment:'Insufficient information',constraints:[],concerns:[],unknowns:[],facts:[],whatChanges:[],limitations:[]}},'plan-record');
}

test('legacy Journal records load with empty additive trade notes and round-trip without losing old fields',()=>{
 const legacy={version:1,draft:null,records:[record()],savedAnalyses:[Workspace.importAnalysis(analysisPacket())],savedDrafts:[],selectedId:null,updatedAt:null};
 const loaded=Workspace.readState({getItem:()=>JSON.stringify(legacy)});
 assert.equal(loaded.warning,'');assert.deepEqual(loaded.state.tradeNotes,[]);
 assert.deepEqual(loaded.state.records,legacy.records);assert.deepEqual(loaded.state.savedAnalyses,legacy.savedAnalyses);
 const note={key:Workspace.tradeKey(trade()),text:'Keep the planned risk.',draftText:'Keep the planned risk; wait for the close.',updatedAt:'2026-10-20T02:00:00Z'};
 loaded.state.tradeNotes.push(note);
 let persisted;assert.equal(Workspace.writeState({setItem(_key,value){persisted=value;}},loaded.state),'');
 const restored=Workspace.readState({getItem:()=>persisted});assert.equal(restored.warning,'');assert.deepEqual(restored.state.tradeNotes,[note]);
 const exported=Workspace.exportRecord(restored.state);assert.deepEqual(exported.tradeNotes,[note]);assert.deepEqual(exported.records,legacy.records);
 exported.tradeNotes[0].text='Mutated export';assert.equal(restored.state.tradeNotes[0].text,note.text);
});

test('paper trade IDs distinguish repeated tickets, markets, opening times and closing times',()=>{
 const first=trade();const variants=[first,trade({sym:'SECOND'}),trade({openTime:first.openTime+1}),trade({closeTime:first.closeTime+1}),trade({id:'ticket-2'})];
 assert.equal(new Set(variants.map(Workspace.tradeKey)).size,variants.length);
 assert.equal(Workspace.tradeKey(clone(first)),Workspace.tradeKey(first));
 assert.notEqual(Workspace.tradeKey(trade({id:'a|b',sym:'c'})),Workspace.tradeKey(trade({id:'a',sym:'b|c'})));
});

test('rendering trade history and details escapes user-supplied trade values',()=>{
 const attack='<img src=x onerror="alert(1)">';const t=trade({id:attack,sym:attack,pair:attack,type:'<script>bad()</script>',volume:'<b>1</b>',reason:attack});
 const h=mounted({trades:[t]});h.api.open({history:true});
 assert.match(h.dialog.innerHTML,/&lt;img src=x onerror=&quot;alert\(1\)&quot;&gt;/);assert.doesNotMatch(h.dialog.innerHTML,/<img|<script|<b>1<\/b>/i);
 h.click('trade',{id:Workspace.tradeKey(t)});assert.match(h.dialog.innerHTML,/&lt;img src=x onerror=&quot;alert\(1\)&quot;&gt;/);assert.doesNotMatch(h.dialog.innerHTML,/<img|<script|<b>1<\/b>/i);
 h.typeNote('<script>not executable</script>');h.click('save-trade-note');assert.match(h.dialog.innerHTML,/&lt;script&gt;not executable&lt;\/script&gt;/);assert.doesNotMatch(h.dialog.innerHTML,/<script>/i);
});

test('each trade retains its own saved reflection and independent unfinished revision through switching and reload',()=>{
 const first=trade(),second=trade({sym:'SECOND',pair:'SECOND/USD'}),h=mounted({trades:[first,second]});h.api.open({history:true});
 h.click('trade',{id:Workspace.tradeKey(first)});h.typeNote('Followed the original risk plan.');h.click('save-trade-note');
 h.typeNote('Followed the original risk plan. Next time wait for the close.');
 h.click('history',{section:'trades'});h.click('trade',{id:Workspace.tradeKey(second)});assert.equal(h.elements['ow-trade-reflection'].value,'');
 h.typeNote('Second trade needs a separate reflection.');h.click('save-trade-note');
 h.click('trade',{id:Workspace.tradeKey(first)});assert.equal(h.elements['ow-trade-reflection'].value,'Followed the original risk plan. Next time wait for the close.');
 const notes=h.api.getState().tradeNotes,firstNote=notes.find(n=>n.key===Workspace.tradeKey(first)),secondNote=notes.find(n=>n.key===Workspace.tradeKey(second));
 assert.equal(firstNote.text,'Followed the original risk plan.');assert.notEqual(firstNote.draftText,firstNote.text);assert.equal(secondNote.text,'Second trade needs a separate reflection.');assert.equal(secondNote.draftText,secondNote.text);
 const reloaded=mounted({saved:h.stored(),trades:[first,second]});reloaded.api.open({history:true});reloaded.click('trade',{id:Workspace.tradeKey(first)});
 assert.equal(reloaded.elements['ow-trade-reflection'].value,firstNote.draftText);assert.deepEqual(reloaded.api.exportRecord(reloaded.api.getState()).tradeNotes,notes);
});

test('failed explicit reflection save retains the previous saved note and current draft with no success message',()=>{
 const t=trade(),h=mounted({trades:[t]});h.api.open({history:true});h.click('trade',{id:Workspace.tradeKey(t)});
 h.typeNote('Original saved takeaway.');h.click('save-trade-note');h.typeNote('A new takeaway is still being written.');const before=h.api.getState().tradeNotes,raw=h.raw();
 h.failStorage();h.click('save-trade-note');
 assert.deepEqual(h.api.getState().tradeNotes,before);assert.equal(h.raw(),raw);assert.equal(h.elements['ow-trade-reflection'].value,'A new takeaway is still being written.');
 assert.match(h.dialog.innerHTML,/Could not save\. Your draft is still here\./);assert.doesNotMatch(h.dialog.innerHTML,/Reflection saved\./);assert.match(h.elements.owSave.textContent,/could not save/i);
 h.failStorage(false);h.click('save-trade-note');assert.equal(h.api.getState().tradeNotes[0].text,'A new takeaway is still being written.');assert.match(h.dialog.innerHTML,/Reflection saved\./);
});

test('a draft remains available for export when browser storage fails while typing',()=>{
 const t=trade(),h=mounted({trades:[t]});h.api.open({history:true});h.click('trade',{id:Workspace.tradeKey(t)});h.failStorage();
 h.typeNote('My unsaved reflection must remain in this session.');h.click('save-trade-note');
 assert.equal(h.api.getState().tradeNotes[0].text,'');assert.equal(h.api.exportRecord(h.api.getState()).tradeNotes[0].draftText,'My unsaved reflection must remain in this session.');
 assert.equal(h.elements['ow-trade-reflection'].value,'My unsaved reflection must remain in this session.');assert.doesNotMatch(h.dialog.innerHTML,/Reflection saved\./);
});

test('reflection status immediately distinguishes an edited draft and each explicit save writes once',()=>{
 const t=trade(),h=mounted({trades:[t]});h.api.open({history:true});h.click('trade',{id:Workspace.tradeKey(t)});
 h.typeNote('First useful takeaway.');assert.match(h.elements.owNoteStatus.textContent,/Draft saved/);
 const before=h.writes();h.click('save-trade-note');assert.equal(h.writes(),before+1);assert.equal(h.stored().tradeNotes[0].text,'First useful takeaway.');
 h.typeNote('An unfinished revision.');assert.match(h.elements.owNoteStatus.textContent,/Draft saved/);assert.doesNotMatch(h.elements.owNoteStatus.textContent,/Reflection saved/);
 h.failStorage();h.typeNote('An unavailable-storage revision.');assert.match(h.elements.owNoteStatus.textContent,/Draft not saved/);assert.equal(h.api.getState().tradeNotes[0].text,'First useful takeaway.');
});

test('switching Journal sections and reading saved items does not mutate records, drafts or frozen reviews',()=>{
 const h=mounted();h.api.open();h.type('observation','An unfinished observation retained independently of navigation.');h.api.saveAnalysis(analysisPacket());
 const before=h.api.getState(),raw=h.raw(),writes=h.writes();h.api.open({history:true});
 for(const section of ['plans','reviews','trades','reviews'])h.click('home-tab',{section});
 h.click('read-analysis',{id:'saved-reading'});h.click('history',{section:'reviews'});
 const after=h.api.getState();for(const key of ['draft','savedDrafts','records','savedAnalyses','tradeNotes','updatedAt'])assert.deepEqual(after[key],before[key],key);
 assert.equal(h.raw(),raw);assert.equal(h.writes(),writes);
});

test('a missing paper trade shows a recovery route and keeps its reflection in the export',()=>{
 const t=trade(),h=mounted({trades:[t]});h.api.open({history:true});h.click('trade',{id:Workspace.tradeKey(t)});h.typeNote('Remember the original decision.');h.click('save-trade-note');
 const notes=h.api.getState().tradeNotes;h.trades.splice(0);h.click('trade',{id:Workspace.tradeKey(t)});
 assert.match(h.dialog.innerHTML,/Trade unavailable/);assert.match(h.dialog.innerHTML,/Back to trades/);assert.deepEqual(h.api.exportRecord(h.api.getState()).tradeNotes,notes);
 h.click('history',{section:'trades'});assert.match(h.dialog.innerHTML,/Your trades will appear here/);
});

test('a saved Oracle review opens without a plan and its handoff keeps frozen evidence without replacing unfinished writing',()=>{
 const h=mounted();const packet=analysisPacket();h.api.saveAnalysis(packet);h.api.open({history:true,section:'reviews'});h.click('read-analysis',{id:packet.id});
 assert.equal(h.api.getState().draft,null);assert.match(h.dialog.innerHTML,/The captured market remains inside its observed range\./);
 h.click('new');h.type('observation','Keep this unrelated draft while exploring a saved review.');const existing=h.api.getState().draft;
 h.click('read-analysis',{id:packet.id});h.click('add-plan',{id:packet.id});assert.equal(h.api.getState().screen,'draft-choice');assert.deepEqual(h.api.getState().draft,existing);
 h.click('keep-start');const state=h.api.getState();assert.deepEqual(state.draft.snapshot,packet.snapshot);assert.deepEqual(state.draft.originAnalysis.marketReview,packet.marketReview);assert.deepEqual(state.savedDrafts,[existing]);
 const restored=Workspace.readState({getItem:()=>h.raw()});assert.equal(restored.warning,'');assert.deepEqual(restored.state.draft.snapshot,packet.snapshot);assert.deepEqual(restored.state.savedAnalyses[0].questions,packet.questions);
});

test('trade reflection is optional and never requires or creates a hypothesis plan',()=>{
 const t=trade(),h=mounted({trades:[t]});h.api.open({history:true});h.click('trade',{id:Workspace.tradeKey(t)});
 assert.match(h.dialog.innerHTML,/Optional\. The trade is already logged/);assert.equal(h.api.getState().draft,null);assert.deepEqual(h.api.getState().records,[]);
 h.click('save-trade-note');assert.deepEqual(h.api.getState().tradeNotes,[]);assert.equal(h.api.getState().draft,null);
 h.typeNote('Useful lesson.');h.click('save-trade-note');assert.equal(h.api.getState().tradeNotes[0].text,'Useful lesson.');assert.equal(h.api.getState().draft,null);assert.deepEqual(h.api.getState().records,[]);assert.equal(h.trades.length,1);
});
