import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createAlexConnectionLifecycle} from '../academy/cinematic/alex-support.js';

function harness(){
  let time=0,next=0,active=true;
  const events=[],timers=new Map();
  const connection=createAlexConnectionLifecycle({isActive:()=>active,
    onConnecting:()=>events.push('connecting'),onDelayed:()=>events.push('delayed'),onConnect:()=>events.push('connected'),
    setTimer:(fn,delay)=>{const id=++next;timers.set(id,{fn,at:time+delay});return id},clearTimer:id=>timers.delete(id)});
  return {connection,events,timers,set active(value){active=value},advance(ms){time+=ms;for(const [id,timer] of [...timers])if(timer.at<=time){timers.delete(id);timer.fn()}}};
}
const session=()=>({ends:0,marked:false,endSession(){this.ends++;return Promise.resolve()},markConnected(){this.marked=true}});
// This is the pinned SDK's actual startup order: create callback, mark live,
// connect callback. Startup exceptions go through endSession before rethrow.
async function finishStartup(config,value){
  try{config.onConversationCreated(value);value.markConnected();config.onConnect({conversationId:'demo'})}
  catch(error){await value.endSession();throw error}
}

test('normal connection preserves callbacks, clears its notice and closes the owned session once',async()=>{
  const ui=harness(),value=session(),config={onConversationCreated:()=>ui.events.push('sdk-created'),onConnect:()=>ui.events.push('sdk-connected')};
  ui.connection.bind(config);assert.equal(ui.timers.size,1);
  await finishStartup(config,value);
  assert.deepEqual(ui.events,['connecting','sdk-created','sdk-connected','connected']);assert.equal(ui.timers.size,0);
  ui.connection.dispose();ui.connection.dispose();assert.equal(value.ends,1);
  config.onConnect();assert.equal(value.ends,1);assert.equal(ui.events.length,4);
});

test('closing a pending start rejects a late session before it becomes live and lets SDK cleanup run',async()=>{
  const ui=harness(),value=session(),config={onConversationCreated:()=>ui.events.push('sdk-created'),onConnect:()=>ui.events.push('sdk-connected')};
  ui.connection.bind(config);ui.connection.dispose();ui.active=false;
  await assert.rejects(finishStartup(config,value),{name:'AbortError'});
  assert.equal(value.ends,1);assert.equal(value.marked,false);assert.equal(ui.timers.size,0);assert.deepEqual(ui.events,['connecting']);
});

test('detached panels also reject late sessions even when disposal has not yet run',async()=>{
  const ui=harness(),value=session(),config={};ui.connection.bind(config);ui.active=false;
  await assert.rejects(finishStartup(config,value),{name:'AbortError'});assert.equal(value.ends,1);assert.equal(value.marked,false);
  ui.advance(15000);assert.deepEqual(ui.events,['connecting']);
});

test('replacing a panel keeps old callbacks from affecting the new panel or session',async()=>{
  const old=harness(),current=harness(),first={},second={},oldSession=session(),newSession=session();
  old.connection.bind(first);old.connection.dispose();old.active=false;current.connection.bind(second);
  await finishStartup(second,newSession);
  await assert.rejects(finishStartup(first,oldSession),{name:'AbortError'});first.onConnect();
  assert.equal(oldSession.ends,1);assert.equal(newSession.ends,0);assert.deepEqual(current.events,['connecting','connected']);
  assert.deepEqual(old.events,['connecting']);current.connection.dispose();assert.equal(newSession.ends,1);
});

test('retry gets a fresh notice deadline and stale callbacks cannot clear or close its session',async()=>{
  const ui=harness(),first={},second={},oldSession=session(),newSession=session();ui.connection.bind(first);
  first.onConversationCreated(oldSession);const staleNotice=[...ui.timers.values()][0].fn;ui.advance(10000);
  ui.connection.bind(second);staleNotice();assert.equal(ui.timers.size,1);ui.advance(5000);assert.equal(ui.events.includes('delayed'),false);
  ui.advance(10000);assert.deepEqual(ui.events,['connecting','connecting','delayed']);await finishStartup(second,newSession);
  first.onConnect();assert.equal(oldSession.ends,1);assert.equal(newSession.ends,0);assert.equal(ui.timers.size,0);
  ui.connection.dispose();assert.equal(newSession.ends,1);
});

test('connection errors and closing cancel pending delayed notices',()=>{
  const ui=harness(),first={};ui.connection.bind(first);ui.connection.clearNotice();ui.advance(15000);assert.deepEqual(ui.events,['connecting']);
  ui.connection.bind({});ui.connection.dispose();ui.advance(15000);assert.deepEqual(ui.events,['connecting','connecting']);assert.equal(ui.timers.size,0);
});

test('pinned text and voice SDK both clean up exceptions from onConversationCreated before marking connected',()=>{
  const sdk=readFileSync(new URL('../academy/cinematic/elevenlabs-widget-0.18.3.js',import.meta.url),'utf8');
  assert.match(sdk,/n\.onConversationCreated\?\.\(i\),i\.markConnected\(\),n\.onConnect\?\.\(\{conversationId:r\.conversationId\}\),i\}catch\(e\)\{throw i\?await i\.endSession\(\)/);
  assert.match(sdk,/n\.onConversationCreated\?\.\(r\),r\.markConnected\(\),n\.onConnect\?\.\(\{conversationId:i\.connection\.conversationId\}\),r\}catch\(e\)\{throw r\?await r\.endSession\(\)/);
});
