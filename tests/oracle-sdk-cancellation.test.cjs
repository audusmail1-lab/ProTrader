const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const Transport=require('../static/oracle-conversation.js');
const Evidence=require('../static/oracle-evidence.js');
const sdkSource=fs.readFileSync(path.join(__dirname,'../static/elevenlabs-client-1.28.0.js'),'utf8');
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return{promise,resolve,reject};};
const tick=()=>new Promise(r=>setImmediate(r));
async function until(check){for(let n=0;n<30;n++){if(check())return;await tick();}assert.fail('Expected mocked platform stage was not reached.');}
function platform({permission,secondPermission,handshake=true,wake,worklet,resume,closeFailure=false}={}){
 const sockets=[],streams=[],contexts=[],audios=[],locks=[],stages=[],states=[];let permissionCalls=0;
 const emitter=()=>({listeners:{},addEventListener(k,f,o={}){(this.listeners[k]||=[]).push({f,once:o.once});},removeEventListener(k,f){this.listeners[k]=(this.listeners[k]||[]).filter(x=>x.f!==f);},emit(k,value){const listeners=[...(this.listeners[k]||[])];this.listeners[k]=(this.listeners[k]||[]).filter(x=>!x.once);for(const {f} of listeners)f(value);}});
 const stream=()=>{const track={stops:0,stop(){this.stops++;},getSettings:()=>({})};const value={track,getTracks:()=>[track],getAudioTracks:()=>[track]};streams.push(value);return value;};
 class Socket{constructor(){Object.assign(this,emitter());this.closes=0;sockets.push(this);if(handshake)queueMicrotask(()=>this.complete());}complete(){this.emit('open',{});this.emit('message',{data:JSON.stringify({type:'conversation_initiation_metadata',conversation_initiation_metadata_event:{conversation_id:'conv_sdk_test',agent_output_audio_format:'pcm_16000',user_input_audio_format:'pcm_16000'}})});}send(){}close(){this.closes++;}}
 const audioNode=()=>({connect(){},disconnect(){},frequencyBinCount:16,fftSize:32,getByteFrequencyData(){},getFloatTimeDomainData(){},gain:{value:1,cancelScheduledValues(){},exponentialRampToValueAtTime(){}}});
 class Context{constructor(){this.state='running';this.sampleRate=16000;this.closes=0;contexts.push(this);this.audioWorklet={addModule:()=>worklet?worklet.promise:Promise.resolve()};}createAnalyser(){return audioNode();}createGain(){return audioNode();}createMediaStreamDestination(){return{...audioNode(),stream:{}};}createMediaStreamSource(){return audioNode();}resume(){return resume?resume.promise:Promise.resolve();}close(){this.closes++;this.state='closed';return closeFailure?Promise.reject(Error('Mock context close failed')):Promise.resolve();}}
 class Audio{constructor(){this.style={};this.pauses=0;this.parentNode=null;audios.push(this);}load(){}pause(){this.pauses++;}remove(){this.parentNode=null;}play(){return Promise.resolve();}}
 class Worklet{constructor(){this.port={...emitter(),postMessage(){},start(){}};}connect(){}}
 const doc={...emitter(),visibilityState:'visible',body:{appendChild(a){a.parentNode={removeChild:x=>{x.parentNode=null;}};}}};
 const nav={userAgent:'Desktop fixture',platform:'Linux',mediaDevices:{getSupportedConstraints:()=>({sampleRate:true}),getUserMedia(){permissionCalls++;return permissionCalls===1&&permission?permission.promise:permissionCalls===2&&secondPermission?secondPermission.promise:Promise.resolve(stream());}},permissions:{query:async()=>({...emitter(),state:'granted'})},wakeLock:{request:async()=>{if(wake)return wake.promise;const lock={released:false,releases:0,release(){this.released=true;this.releases++;return Promise.resolve();}};locks.push(lock);return lock;}}};
 const context={console,setTimeout,clearTimeout,setInterval,clearInterval,queueMicrotask,URL,URLSearchParams,TextEncoder,TextDecoder,DOMException,Error,AbortController,Blob,Uint8Array,ArrayBuffer,DataView,btoa,atob,WebSocket:Socket,AudioContext:Context,Audio,AudioWorkletNode:Worklet,navigator:nav,document:doc,fetch:async()=>{throw Error('NETWORK_DISABLED');}};
 context.window=context;vm.createContext(context);vm.runInContext(sdkSource,context);
 const controller=new AbortController();
 const connect=(textOnly=false)=>context.ElevenLabsClient.Conversation.startSession({signedUrl:'wss://api.elevenlabs.io/fixture',connectionType:'websocket',textOnly,signal:controller.signal,onConnectionStage:s=>stages.push(s),onStatusChange:s=>states.push(s.status)});
 return{sdk:context.ElevenLabsClient,controller,connect,stream,sockets,streams,contexts,audios,locks,stages,states,doc,get permissionCalls(){return permissionCalls;}};
}
function evidence(){const asOf=1800000000;const series={};for(const [tf,sec]of[['15m',900],['1h',3600]]){const end=Math.floor(asOf/sec)*sec;series[tf]={status:'ready',source:'Deriv',capturedAt:asOf+1,candles:Array.from({length:40},(_,i)=>({time:end-(40-i)*sec,open:100+i,high:102+i,low:99+i,close:101+i}))};}return Evidence.extract({id:'sdk-fixture',symbol:'CASE',provider:'Deriv',asOf,capturedAt:asOf+1,dataReference:'fixture',series},'15m');}
function transport(p,options={}){const statuses=[],errors=[];const instance=Transport.create({getEvidence:evidence,onStatus:s=>statuses.push(s),onError:e=>errors.push(e)},{startupTimeoutMs:options.startupTimeoutMs||30000,loadSDK:async()=>p.sdk,fetch:async url=>({ok:true,json:async()=>url.endsWith('/status')?{configured:true}:{signed_url:'wss://api.elevenlabs.io/fixture'}})});return{instance,statuses,errors};}
function assertClean(p){assert.ok(p.streams.every(s=>s.track.stops>0),'every acquired microphone track stopped');assert.ok(p.sockets.every(s=>s.closes>0),'every opened socket closed');assert.ok(p.contexts.every(c=>c.closes>0),'every audio context closed');assert.ok(p.audios.every(a=>!a.parentNode&&a.pauses>0),'audio elements paused and removed');assert.ok(p.locks.every(l=>l.releases>0),'wake locks released');}
test('pinned SDK: ignored permission cancellation resolves promptly; late permission never creates a socket',async()=>{
 const permission=deferred(),p=platform({permission}),t=transport(p);const pending=t.instance.connect({mode:'voice'});await until(()=>p.permissionCalls===1);assert.equal(t.statuses.at(-1).stage,'microphone');await t.instance.disconnect();await pending;assert.equal(t.instance.getState().state,'disconnected');const late=p.stream();permission.resolve(late);await tick();assert.equal(late.track.stops,1);assert.equal(p.sockets.length,0);assertClean(p);
});
test('pinned SDK: denied microphone permission closes acquired resources and text retry succeeds',async()=>{
 const permission=deferred(),p=platform({permission}),t=transport(p);const pending=t.instance.connect({mode:'voice'});await until(()=>p.permissionCalls===1);permission.reject(new DOMException('Microphone denied','NotAllowedError'));await assert.rejects(pending,/Microphone denied/);assert.equal(t.instance.getState().state,'disconnected');await t.instance.connect({mode:'text'});assert.equal(t.instance.getState().state,'connected');assert.equal(p.permissionCalls,1);await t.instance.disconnect();await tick();assertClean(p);
});
test('pinned SDK: startup deadline cancels ignored permission and stops a later granted stream',async()=>{
 const permission=deferred(),p=platform({permission}),t=transport(p,{startupTimeoutMs:15});await assert.rejects(t.instance.connect({mode:'voice'}),/Microphone permission was not completed/);assert.equal(t.instance.getState().state,'disconnected');permission.resolve(p.stream());await tick();assert.equal(p.sockets.length,0);assertClean(p);
});
test('pinned SDK: pending socket handshake cancellation closes socket, microphone and wake lock',async()=>{
 const p=platform({handshake:false}),t=transport(p),pending=t.instance.connect({mode:'voice'});await until(()=>p.sockets.length===1);await t.instance.disconnect();await pending;await tick();assertClean(p);p.sockets[0].complete();await tick();assert.equal(t.instance.getState().state,'disconnected');assert.equal(p.contexts.length,0);
});
test('pinned SDK: late wake lock is released without requesting microphone or opening socket',async()=>{
 const wake=deferred(),p=platform({wake}),pending=p.connect();p.controller.abort();await assert.rejects(pending,/cancel|abort/i);const lock={releases:0,release(){this.releases++;}};wake.resolve(lock);await tick();assert.equal(lock.releases,1);assert.equal(p.permissionCalls,0);assert.equal(p.sockets.length,0);
});
test('pinned SDK: cancellation during audio worklet setup closes both contexts and pending socket',async()=>{
 const worklet=deferred(),p=platform({worklet}),pending=p.connect();await until(()=>p.contexts.length===2);p.controller.abort();await assert.rejects(pending,/cancel|abort/i);await tick();assertClean(p);worklet.resolve();await tick();assert.equal(p.permissionCalls,1,'cancelled worklet completion cannot start second microphone request');
});
test('pinned SDK: late second microphone stops after cancellation and no half-created output leaks',async()=>{
 const secondPermission=deferred(),p=platform({secondPermission}),pending=p.connect();await until(()=>p.permissionCalls===2);p.controller.abort();await assert.rejects(pending,/cancel|abort/i);const late=p.stream();secondPermission.resolve(late);await tick();assert.equal(late.track.stops,1);assertClean(p);
});
test('pinned SDK: cancellation during audio resume closes streams even when context close rejects',async()=>{
 const resume=deferred(),p=platform({resume,closeFailure:true}),pending=p.connect();await until(()=>p.permissionCalls===2);p.controller.abort();await assert.rejects(pending,/cancel|abort/i);await tick();assertClean(p);resume.resolve();await tick();
});
test('pinned SDK: connected voice end starts all cleanup even when wake-lock release never settles',async()=>{
 const p=platform(),session=await p.connect();assert.equal(p.states.at(-1),'connected');p.locks[0].release=function(){this.releases++;return new Promise(()=>{});};session.endSession();await tick();assertClean(p);
});
test('pinned SDK: cancelled voice can retry voice and text without old permission affecting replacement',async()=>{
 const permission=deferred(),p=platform({permission}),t=transport(p),old=t.instance.connect({mode:'voice'});await until(()=>p.permissionCalls===1);await t.instance.disconnect();await old;await t.instance.connect({mode:'voice'});assert.equal(t.instance.getState().state,'connected');const count=p.sockets.length;permission.resolve(p.stream());await tick();assert.equal(p.sockets.length,count);assert.equal(t.instance.getState().state,'connected');await t.instance.connect({mode:'text'});assert.equal(t.instance.getState().mode,'text');await t.instance.disconnect();await tick();assertClean(p);
});
test('pinned SDK: direct text startup also cancels a pending handshake',async()=>{
 const p=platform({handshake:false}),pending=p.connect(true);await until(()=>p.sockets.length===1);p.controller.abort();await assert.rejects(pending,/cancel|abort/i);assert.equal(p.permissionCalls,0);assertClean(p);
});
test('pinned SDK: input permission failure after handshake also closes a completed peer output',async()=>{
 const secondPermission=deferred(),p=platform({secondPermission}),pending=p.connect();await until(()=>p.permissionCalls===2);await tick();secondPermission.reject(new DOMException('Second microphone denied','NotAllowedError'));await assert.rejects(pending,/Second microphone denied/);await tick();assertClean(p);
});
test('pinned SDK: startup timeout covers a silent provider handshake without leaking the microphone',async()=>{
 const p=platform({handshake:false}),t=transport(p,{startupTimeoutMs:15});await assert.rejects(t.instance.connect({mode:'voice'}),/connection took too long/);await tick();assertClean(p);assert.equal(t.instance.getState().state,'disconnected');
});
test('pinned SDK: analyst Cancel preserves a private draft and makes text retry available',async()=>{
 const permission=deferred(),p=platform({permission});let instance;let stored=null;
 global.OracleEvidence=Evidence;global.OracleConversation={create(c){instance=Transport.create(c,{loadSDK:async()=>p.sdk,fetch:async url=>({ok:true,json:async()=>url.endsWith('/status')?{configured:true}:{signed_url:'wss://api.elevenlabs.io/fixture'}})});return instance;}};
 global.localStorage={getItem:()=>stored,setItem:(_key,value)=>stored=value};
 const element=()=>({innerHTML:'',open:false,events:{},addEventListener(k,f){this.events[k]=f;},setAttribute(){},showModal(){this.open=true;},close(){this.open=false;}}),panel=element(),dialog=element();
 const doc={body:{appendChild(){}},createElement:()=>dialog,getElementById:id=>id==='oracle-panel'?panel:null};
 const asOf=1800000000,series={};for(const [tf,sec]of[['15m',900],['1h',3600]]){const end=Math.floor(asOf/sec)*sec;series[tf]={status:'ready',source:'Deriv',capturedAt:asOf+1,candles:Array.from({length:40},(_,i)=>({time:end-(40-i)*sec,open:100+i,high:102+i,low:99+i,close:101+i}))};}
 const snapshot={id:'cancel-ui',symbol:'CASE',label:'Fictional case',provider:'Deriv',asOf,capturedAt:asOf+1,dataReference:'fixture',series};
 delete require.cache[require.resolve('../static/oracle-analyst.js')];const api=require('../static/oracle-analyst.js');api.mount(doc,{getContext:()=>({symbol:'CASE',label:'Fictional case',timeframe:'15m'}),captureSnapshot:async()=>snapshot});await api.refresh();
 panel.events.input({target:{matches:()=>true,value:'My private draft'}});const click=oa=>panel.events.click({target:{closest:()=>({dataset:{oa},closest:()=>panel})}});
 click('connect-voice');await until(()=>p.permissionCalls===1);assert.match(panel.innerHTML,/Waiting for microphone permission/);click('disconnect');await tick();assert.match(panel.innerHTML,/Conversation disconnected/);assert.doesNotMatch(panel.innerHTML,/Cancel connection/);assert.equal(api.getPacket().draft,'My private draft');assert.equal(JSON.parse(stored).active.draft,'My private draft');
 permission.resolve(p.stream());await tick();assert.equal(p.sockets.length,0);click('connect-text');await until(()=>instance.getState().state==='connected');assert.match(panel.innerHTML,/Connected · text/);assert.equal(api.getPacket().draft,'My private draft');click('disconnect');await tick();assertClean(p);
});
