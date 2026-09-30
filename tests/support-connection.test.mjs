import test from 'node:test';
import assert from 'node:assert/strict';

globalThis.window=new EventTarget();
globalThis.document=undefined;
const {initSupport}=await import('../academy/support-chat.js');
const empty={aiAvailable:false,thread:null,status:'new',messages:[]};
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {promise,resolve,reject}};

// Focus, disabled state and event handlers are exercised on the real controller.
// Layout/browser rendering is covered separately in the hands-on preview audit.
function mount(t,fetch){
 const nodes=new Map();let focused=null;
 class Node extends EventTarget{
  hidden=false;disabled=false;value='';checked=false;innerHTML='';textContent='';
  classList={toggle(){}};
  setAttribute(){}
  focus(){focused=this}
  replaceChildren(){this.innerHTML=''}
  querySelector(selector){if(!nodes.has(selector)){const node=new Node();node.hidden=selector==='#chat-window'||selector==='#chat-retry';nodes.set(selector,node)}return nodes.get(selector)}
 }
 const document=new EventTarget();document.createElement=()=>new Node();document.body={append(){}};
 t.mock.property(globalThis,'document',document);
 t.mock.property(globalThis,'window',new EventTarget());
 t.mock.method(globalThis,'fetch',fetch);
 t.mock.method(globalThis,'setInterval',()=>1);
 const support=initSupport({humanOnly:true,showLauncher:false});
 t.after(()=>support.close());
 return {support,q:selector=>nodes.get(selector),focused:()=>focused};
}

test('first send waits for support identity while the visitor can immediately write',async t=>{
 const connection=deferred(),calls=[];
 const ui=mount(t,async(url,options)=>{calls.push({url,options});return connection.promise});
 const opening=ui.support.open();
 assert.equal(ui.focused(),ui.q('#chat-body'));
 assert.equal(ui.q('#chat-send').disabled,true);
 ui.q('#chat-body').value='My class question';
 ui.q('#chat-form').onsubmit({preventDefault(){}});
 assert.equal(calls.length,1);assert.equal(calls[0].options.method,'GET');
 connection.resolve(Response.json(empty));await opening;
 assert.equal(ui.q('#chat-send').disabled,false);
 assert.equal(ui.q('#chat-body').value,'My class question');
});

test('failed identity setup offers retry and preserves the draft',async t=>{
 let attempts=0;
 const ui=mount(t,async()=>{if(++attempts===1)throw new TypeError('Network unavailable');return Response.json(empty)});
 const opening=ui.support.open();
 ui.q('#chat-body').value='Please help with my classroom';
 await opening;
 assert.equal(ui.q('#chat-send').disabled,true);
 assert.equal(ui.q('#chat-retry').hidden,false);
 assert.match(ui.q('#chat-error').textContent,/draft is safe/);
 await ui.q('#chat-retry').onclick();
 assert.equal(ui.q('#chat-retry').hidden,true);
 assert.equal(ui.q('#chat-send').disabled,false);
 assert.equal(ui.q('#chat-body').value,'Please help with my classroom');
});

test('a lost first message response retains its identity and draft for a deliberate retry',async t=>{
 const writes=[];
 const ui=mount(t,async(url,options)=>{
  if(options.method==='GET')return Response.json(empty);
  writes.push(JSON.parse(options.body));
  if(writes.length===1)throw new TypeError('Connection ended');
  return Response.json({...empty,thread:1,status:'waiting'});
 });
 await ui.support.open();ui.q('#chat-body').value='Where is my class?';
 ui.q('#chat-form').onsubmit({preventDefault(){}});await tick();
 assert.equal(writes.length,1);assert.equal(ui.q('#chat-body').value,'Where is my class?');
 assert.match(ui.q('#chat-error').textContent,/could not confirm/);
 ui.q('#chat-form').onsubmit({preventDefault(){}});await tick();
 assert.equal(writes.length,2);assert.equal(writes[0].clientId,writes[1].clientId);
 assert.equal(ui.q('#chat-body').value,'');
});

test('session change requires fresh identity and ignores the old connection response',async t=>{
 const old=deferred(),fresh=deferred();let reads=0;
 const ui=mount(t,async()=>++reads===1?old.promise:fresh.promise);
 const first=ui.support.open();
 window.dispatchEvent(new Event('academy-session-changed'));
 const second=ui.support.open();
 old.resolve(Response.json({...empty,thread:99}));await first;
 assert.equal(ui.q('#chat-send').disabled,true);
 fresh.resolve(Response.json(empty));await second;
 assert.equal(ui.q('#chat-send').disabled,false);assert.equal(reads,2);
});
