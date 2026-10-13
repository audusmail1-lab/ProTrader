import test from 'node:test';
import assert from 'node:assert/strict';
import {ALEX_AGENT_ID,createAlexLoader} from '../academy/cinematic/alex-loader.js';
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no});return {promise,resolve,reject}};
const config=extra=>({variant:'full',placement:'bottom-right',language:'en',avatar:{type:'orb',color_1:'#111111',color_2:'#eeeeee'},text_contents:{},styles:{},language_presets:{},terms_html:null,terms_text:null,terms_key:null,...extra});
const response=value=>({ok:true,json:async()=>({agent_id:ALEX_AGENT_ID,widget_config:value})});
function harness(overrides={}){
 let now=1000000,nextTimer=0,stored=null,calls=0;
 const timers=new Map(),scripts=[],definitions=new Map(),defined=deferred();
 const clock={now:()=>now,setTimer:(fn,delay)=>{const id=++nextTimer;timers.set(id,{fn,at:now+delay});return id},clearTimer:id=>timers.delete(id)};
 const storage={getItem:()=>stored,setItem:(_,value)=>{stored=value}};
 const registry={get:name=>definitions.get(name),whenDefined:()=>defined.promise};
 const document={createElement:()=>({remove(){this.removed=true}}),head:{append(script){scripts.push(script)}}};
 const loader=createAlexLoader({...clock,storage:()=>storage,document:()=>document,registry:()=>registry,fetch:()=>{calls++;return new Promise(()=>{})},...overrides});
 return {loader,scripts,timers,get calls(){return calls},get stored(){return stored},set stored(value){stored=value},define(){definitions.set('elevenlabs-convai',class {});defined.resolve()},advance(ms){now+=ms;for(const [id,timer] of [...timers])if(timer.at<=now){timers.delete(id);timer.fn()}}};
}
test('local settings mount immediately while refresh is slow and mounted snapshots never change',async()=>{
 const request=deferred();let calls=0;const ui=harness({fetch:()=>{calls++;return request.promise}});
 const settings=ui.loader.getAlexSettings();assert.equal(settings.language,'en');assert.equal(settings.supports_text_only,true);
 assert.match(settings.first_message,/Hi, I’m Alex/);assert.equal(settings.styles.base,'#141d18');assert.equal(typeof settings.then,'undefined');
 ui.advance(24000);ui.loader.getAlexSettings();await tick();assert.equal(calls,1);
 request.resolve(response(config({terms_html:'Please read our terms',terms_key:'terms-v2'})));await tick();
 assert.equal(settings.terms_html,null);assert.equal(ui.loader.getAlexSettings().terms_key,'terms-v2');
 assert.equal(JSON.parse(ui.stored).at,1024000);
});
test('rejected refresh never blocks and repeated opens respect cooldown',async()=>{
 let calls=0;const ui=harness({fetch:async()=>{calls++;throw new TypeError('Failed to fetch')}});
 assert.equal(ui.loader.getAlexSettings().language,'en');await tick();
 for(let i=0;i<5;i++)ui.loader.getAlexSettings();await tick();assert.equal(calls,1);
 ui.advance(30000);ui.loader.getAlexSettings();await tick();assert.equal(calls,2);
});
test('hung refresh is bounded even when transport ignores abort and late responses cannot overwrite newer settings',async()=>{
 const first=deferred(),second=deferred();let calls=0,signal;
 const ui=harness({fetch:(_,options)=>{signal=options.signal;return ++calls===1?first.promise:second.promise}});
 ui.loader.getAlexSettings();await tick();ui.advance(30000);await tick();assert.equal(signal.aborted,true);
 ui.loader.getAlexSettings();await tick();assert.equal(calls,2);
 second.resolve(response(config({terms_key:'new-policy',terms_html:'New terms'})));await tick();
 first.resolve(response(config({terms_key:'old-policy',terms_html:'Old terms'})));await tick();
 assert.equal(ui.loader.getAlexSettings().terms_key,'new-policy');
});
test('stale and future-dated caches preserve known terms and localized policy when refresh fails',async()=>{
 for(const at of [0,9999999999]){
  const ui=harness({fetch:async()=>{throw Error('unavailable')}});
  ui.stored=JSON.stringify({agent:ALEX_AGENT_ID,at,config:config({terms_html:'Read before calling',terms_text:'Read',terms_key:'terms-required',language_presets:{fr:{terms_html:'Conditions',terms_key:'terms-fr'}}})});
  const settings=ui.loader.getAlexSettings();await tick();assert.equal(settings.terms_key,'terms-required');assert.equal(settings.terms_html,'Read before calling');assert.equal(ui.loader.getAlexSettings().language_presets.fr.terms_key,'terms-fr');
 }
});
test('fresh cache avoids requests and returned settings are detached',async()=>{
 const ui=harness();ui.stored=JSON.stringify({agent:ALEX_AGENT_ID,at:999999,config:config({terms_html:'Current terms',terms_key:'v1'})});
 const first=ui.loader.getAlexSettings(),second=ui.loader.getAlexSettings();first.terms_html=null;first.styles.base='broken';
 assert.equal(second.terms_html,'Current terms');assert.equal(second.styles.base,'#141d18');await tick();assert.equal(ui.calls,0);
});
test('unavailable storage, malformed cache and malformed responses retain reviewed settings',async()=>{
 for(const storage of [()=>{throw Error('private mode')},()=>({getItem:()=>'{broken',setItem:()=>{throw Error('quota')}})]){
  const ui=harness({storage,fetch:async()=>response(config())});assert.equal(ui.loader.getAlexSettings().language,'en');await tick();assert.equal(ui.loader.getAlexSettings().language,'en');
 }
 for(const value of [null,[],{},config({avatar:null}),config({language:'unsupported'}),config({supports_text_only:'yes'}),config({language_presets:[]}),config({terms_html:42}),config({supported_language_overrides:{}})]){
  const ui=harness({fetch:async()=>response(value)});ui.loader.getAlexSettings();await tick();assert.equal(ui.loader.getAlexSettings().supports_text_only,true);assert.equal(ui.stored,null);
 }
 const wrong=harness({fetch:async()=>({ok:true,json:async()=>({agent_id:'another-agent',widget_config:config()})})});wrong.loader.getAlexSettings();await tick();assert.equal(wrong.stored,null);
});
test('concurrent widget callers share one script and registration completes them',async()=>{
 const ui=harness(),first=ui.loader.loadAlexWidget(),second=ui.loader.loadAlexWidget();assert.equal(first,second);assert.equal(ui.scripts.length,1);assert.equal(ui.scripts[0].src,'/cinematic/elevenlabs-widget-0.18.3.js');
 ui.define();await first;assert.equal(ui.timers.size,0);await ui.loader.loadAlexWidget();assert.equal(ui.scripts.length,1);
});
test('definitive network failures retry once and later deliberate retry recovers',async()=>{
 const ui=harness(),first=ui.loader.loadAlexWidget();ui.scripts[0].onerror();assert.equal(ui.scripts[0].removed,true);assert.equal(ui.scripts.length,2);
 const failed=assert.rejects(first,/could not load/);ui.scripts[1].onerror();await failed;
 const next=ui.loader.loadAlexWidget();assert.equal(ui.scripts.length,3);ui.define();await next;
});
test('timeout retains the script; late load settles the next attempt without duplicate evaluation',async()=>{
 const ui=harness(),first=ui.loader.loadAlexWidget(),failed=assert.rejects(first,/could not load/);
 const lateLoad=ui.scripts[0].onload;ui.advance(30000);await failed;assert.equal(ui.scripts[0].removed,undefined);
 const next=ui.loader.loadAlexWidget();assert.equal(ui.scripts.length,1);ui.define();lateLoad();await next;assert.equal(ui.scripts.length,1);assert.equal(ui.timers.size,0);
});
test('loaded script without registration fails and a deliberate retry can initialize',async()=>{
 const ui=harness(),first=ui.loader.loadAlexWidget(),failed=assert.rejects(first,/did not initialize/);ui.scripts[0].onload();await failed;assert.equal(ui.scripts[0].removed,true);
 const next=ui.loader.loadAlexWidget();assert.equal(ui.scripts.length,2);ui.define();await next;
});
test('synchronous document failure does not poison later retries',async()=>{
 let blocked=true;const ui=harness({document:()=>{if(blocked)throw Error('document unavailable');return {createElement:()=>({remove(){}}),head:{append(){}}}}});
 await assert.rejects(ui.loader.loadAlexWidget(),/document unavailable/);blocked=false;const next=ui.loader.loadAlexWidget();ui.define();await next;
});
