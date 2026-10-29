const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const html=fs.readFileSync(path.join(__dirname,'../protrader_mobile.html'),'utf8');
const keys={oracleAnalyst:'protrader.oracle.analyst-preview.v1',oracleReviews:'protrader.oracle.learning.v1',lessonPractice:'protrader.lesson.explain-idea.v1'};
function harness(choice='account'){
 const events=[],requests=[];class Storage{constructor(){this.values=new Map();}getItem(k){return this.values.get(k)??null;}setItem(k,v){if(this.fail?.(k,String(v)))throw new Error('QuotaExceededError');events.push(['write',k]);this.values.set(k,String(v));}removeItem(k){events.push(['remove',k]);this.values.delete(k);}}
 const localStorage=new Storage(),sessionStorage=new Storage();
 for(const [key,ls]of Object.entries(keys))localStorage.setItem(ls,JSON.stringify({guest:key}));events.length=0;
 const root={};for(const mod of ['OracleAnalyst','OracleWorkspace','LessonPractice'])root[mod]={clearForAccountChange:()=>events.push(['clear',mod])};
 const c=vm.createContext({window:root,Storage,localStorage,sessionStorage,navigator:{onLine:true},document:{hidden:false,visibilityState:'visible',addEventListener(){},getElementById:()=>null},addEventListener(){},setInterval(){},setTimeout(){return 0;},clearTimeout(){},showToast(){},location:{reload(){events.push(['reload']);}},AbortSignal:{timeout:()=>undefined},
 fetch:async(path,opts)=>{requests.push({path,opts});return{ok:true,status:200,json:async()=>({version:1})};}});
 let source=html.slice(html.indexOf('const ACCOUNT ='),html.indexOf('setTimeout(() => ACCOUNT.boot()'));
 source=source.replace('return { open, boot, isOwner:',`return { test:{adopt,wipe,signedOutElsewhere,put,pull,write,meta:()=>meta,setUser:value=>user=value,setChoice:fn=>ask=fn,docs:DOCS}, open, boot, isOwner:`);
 vm.runInContext(source+';globalThis.a=ACCOUNT;',c);c.a.test.setUser({id:'acct-A',name:'Fixture'});c.a.test.setChoice(async()=>{events.push(['choose',choice]);return choice;});
 return{c,events,requests,localStorage};
}
test('first sign-in asks before moving guest discussions into an empty account',async()=>{
 const h=harness('account');await h.c.a.test.adopt({},true);
 assert.ok(h.events.some(e=>e[0]==='choose'));assert.equal(h.requests.length,0);
 for(const [key,ls]of Object.entries(keys)){
   assert.equal(h.localStorage.getItem(ls),null);
   assert.equal(JSON.parse(h.localStorage.getItem('protrader.education.backup.guest.'+key)).guest,key);
 }
 const firstRemove=h.events.findIndex(e=>e[0]==='remove'&&Object.values(keys).includes(e[1]));
 for(const name of ['OracleAnalyst','OracleWorkspace','LessonPractice'])assert.ok(h.events.findIndex(e=>e[0]==='clear'&&e[1]===name)<firstRemove);
 assert.ok(h.events.some(e=>e[0]==='reload'));
});
test('explicit device choice imports only the chosen records and preserves a guest backup',async()=>{
 const h=harness('device');await h.c.a.test.adopt({},true);
 assert.equal(h.requests.filter(r=>r.opts.method==='PUT').length,3);
 for(const key of Object.keys(keys)){const req=h.requests.find(r=>r.path.endsWith('/'+key));assert.equal(JSON.parse(req.opts.body).data.guest,key);assert.ok(h.localStorage.getItem('protrader.education.backup.guest.'+key));}
});
test('account switch clears module memory before removing all active educational documents',()=>{
 const h=harness();h.c.a.test.wipe();
 for(const key of Object.values(keys))assert.equal(h.localStorage.getItem(key),null);
 const firstRemove=h.events.findIndex(e=>e[0]==='remove');assert.ok(h.events.slice(0,firstRemove).filter(e=>e[0]==='clear').length===3);
 assert.equal(h.c.a.test.docs.oracleReviews,keys.oracleReviews);
});
test('expired account session removes educational state and reports browser-only storage',()=>{
 const h=harness();h.c.a.test.signedOutElsewhere();
 for(const key of Object.values(keys))assert.equal(h.localStorage.getItem(key),null);
 assert.match(h.c.window.ProTraderStorageStatus(),/Guest.*browser only/);assert.ok(h.events.some(e=>e[0]==='reload'));
});

test('oversized account documents remain unsynchronized, visible locally, and are not retried until changed',async()=>{
 const h=harness();let attempts=0;
 h.c.fetch=async()=>{attempts++;return{ok:false,status:413,json:async()=>({detail:'Too large'})};};
 const original=h.localStorage.getItem(keys.oracleAnalyst);
 assert.equal(await h.c.a.test.put('oracleAnalyst'),false);assert.equal(attempts,1);
 assert.equal(h.localStorage.getItem(keys.oracleAnalyst),original);assert.equal(h.c.a.test.meta().h.oracleAnalyst,undefined);
 assert.match(h.c.window.ProTraderStorageStatus(),/exceed.*sync limit/);
 assert.equal(await h.c.a.test.put('oracleAnalyst'),false);assert.equal(attempts,1,'Identical rejected body must not be uploaded again');
 h.localStorage.setItem(keys.oracleAnalyst,JSON.stringify({active:null,history:[]}));
 h.c.fetch=async()=>{attempts++;return{ok:true,status:200,json:async()=>({version:2})};};
 assert.equal(await h.c.a.test.put('oracleAnalyst'),true);assert.equal(attempts,2);assert.equal(h.c.a.test.meta().syncErrors.oracleAnalyst,undefined);
});

test('account storage quota failure leaves the previous local document and synchronization hash intact',()=>{
 const h=harness();const original=h.localStorage.getItem(keys.oracleAnalyst);
 h.localStorage.fail=(key,value)=>key===keys.oracleAnalyst&&value.includes('incoming');
 assert.throws(()=>h.c.a.test.write('oracleAnalyst',{incoming:'new account'}),/storage/);
 assert.equal(h.localStorage.getItem(keys.oracleAnalyst),original);
 assert.equal(h.c.a.test.meta().h.oracleAnalyst,undefined);
 assert.match(h.c.window.ProTraderStorageStatus(),/not applied/);
});
test('failed account adoption rolls back earlier writes and never uploads the old guest scope',async()=>{
 const h=harness();const original=Object.fromEntries(Object.values(keys).map(key=>[key,h.localStorage.getItem(key)]));
 h.localStorage.fail=(key,value)=>key===keys.oracleReviews&&value.includes('incoming');
 const docs={oracleAnalyst:{version:2,data:{incoming:'analyst'}},oracleReviews:{version:2,data:{incoming:'review'}}};
 await assert.rejects(h.c.a.test.adopt(docs,true),/storage/);
 for(const key of Object.values(keys))assert.equal(h.localStorage.getItem(key),original[key]);
 assert.equal(h.c.a.test.meta().uid,undefined);assert.equal(h.c.a.user(),null);
 assert.equal(h.requests.length,0);assert.ok(!h.events.some(e=>e[0]==='reload'));
 assert.match(h.c.window.ProTraderStorageStatus(),/not applied/);
});

test('a delayed account pull cannot restore the departing account after wipe',async()=>{
 const h=harness();let resolve;h.c.fetch=()=>new Promise(r=>resolve=r);
 const request=h.c.a.test.pull();h.c.a.test.wipe();
 resolve({ok:true,status:200,json:async()=>({docs:{oracleAnalyst:{version:3,data:{oldAccount:'private'}}}})});
 await request;
 for(const key of Object.values(keys))assert.equal(h.localStorage.getItem(key),null);
 assert.equal(h.c.a.test.meta().h.oracleAnalyst,undefined);
});
test('a delayed account put cannot commit synchronization metadata after wipe',async()=>{
 const h=harness();let resolve;h.c.fetch=()=>new Promise(r=>resolve=r);
 const request=h.c.a.test.put('oracleAnalyst');h.c.a.test.wipe();
 resolve({ok:true,status:200,json:async()=>({version:8})});await request;
 assert.equal(h.c.a.test.meta().h.oracleAnalyst,undefined);assert.equal(h.c.a.test.meta().v.oracleAnalyst,undefined);
});

test('expired sign-in clears its owner marker so the reload cannot expose old learning or loop',()=>{
 const h=harness();h.c.a.test.meta().uid='acct-A';h.c.a.test.meta().owner=true;
 h.c.a.test.signedOutElsewhere();
 assert.equal(h.c.a.test.meta().uid,undefined);assert.equal(h.c.a.test.meta().owner,false);
 for(const key of Object.values(keys))assert.equal(h.localStorage.getItem(key),null);
 assert.ok(html.includes('if (!user && meta.uid) return signedOutElsewhere();'));
});
test('unavailable backup storage locks expired learning instead of exposing or discarding it',()=>{
 const h=harness();h.c.a.test.meta().uid='acct-A';h.localStorage.fail=key=>key.startsWith('protrader.education.backup.');
 h.c.a.test.signedOutElsewhere();
 assert.equal(h.c.a.user(),null);assert.equal(h.c.a.test.meta().uid,'acct-A');
 for(const key of Object.values(keys))assert.ok(h.localStorage.getItem(key));
 assert.equal(h.events.filter(e=>e[0]==='clear').length,3);
 assert.match(h.c.window.ProTraderStorageStatus(),/locked to the previous account/);
 assert.ok(!h.events.some(e=>e[0]==='reload'));
});

test('backup failure blocks an ordinary account wipe; only explicit sign-out-anyway may discard unsynced local records',()=>{
 const h=harness();h.localStorage.fail=key=>key.startsWith('protrader.education.backup.');
 assert.throws(()=>h.c.a.test.wipe(),/storage/);
 for(const key of Object.values(keys))assert.ok(h.localStorage.getItem(key));
 h.c.a.test.wipe({allowBackupFailure:true});
 for(const key of Object.values(keys))assert.equal(h.localStorage.getItem(key),null);
 assert.match(html,/Signing out anyway removes unsynchronized records[\s\S]*?wipe\(\{allowBackupFailure:true\}\)/);
});
