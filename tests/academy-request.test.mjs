import test from 'node:test';
import assert from 'node:assert/strict';

// The support module's only initialization registers a session-change listener.
globalThis.window=new EventTarget();
const {academyRequest}=await import('../academy/support-chat.js');

test('classroom reads and support writes use the same JSON transport without retries',async t=>{
  const calls=[];
  t.mock.method(globalThis,'fetch',async (url,options)=>{calls.push({url,options});return Response.json({ok:true})});
  assert.deepEqual(await academyRequest('classroom'),{ok:true});
  const message={body:'I have a class question.',clientId:'same-message-on-retry',human:true};
  await academyRequest('support-message',message);
  assert.equal(calls.length,2);
  assert.equal(calls[0].url,'/api/classroom');assert.equal(calls[0].options.method,'GET');
  assert.equal(calls[0].options.body,undefined);
  assert.equal(calls[1].options.method,'POST');
  assert.deepEqual(JSON.parse(calls[1].options.body),message);
  assert.ok(calls[1].options.signal instanceof AbortSignal);
});

test('a stalled read aborts promptly and reports helpful connection guidance',async t=>{
  let signal,calls=0;
  t.mock.method(globalThis,'fetch',(_url,options)=>{calls++;signal=options.signal;return new Promise((_resolve,reject)=>signal.addEventListener('abort',()=>reject(new DOMException('Aborted','AbortError')),{once:true}))});
  await assert.rejects(academyRequest('classroom',undefined,{timeoutMs:5}),error=>error.message.includes('taking longer')&&!error.requestUncertain);
  assert.equal(signal.aborted,true);assert.equal(calls,1);
});

test('a response that stalls while reading its body is also bounded',async t=>{
  let signal;
  t.mock.method(globalThis,'fetch',async (_url,options)=>{
    signal=options.signal;
    return {ok:true,json:()=>new Promise((_resolve,reject)=>signal.addEventListener('abort',()=>reject(new DOMException('Aborted','AbortError')),{once:true}))};
  });
  await assert.rejects(academyRequest('classroom',undefined,{timeoutMs:5}),/taking longer/);
  assert.equal(signal.aborted,true);
});

test('an ambiguous write is never automatically retried or reported as unsaved',async t=>{
  let calls=0;
  t.mock.method(globalThis,'fetch',async()=>{calls++;throw new TypeError('Failed to fetch')});
  await assert.rejects(academyRequest('questions',{lesson:0,body:'A test question'}),error=>error.requestUncertain===true&&error.message.includes('Check whether it saved'));
  assert.equal(calls,1);
});

test('validation and expired-session status survive for the caller to handle',async t=>{
  t.mock.method(globalThis,'fetch',async()=>Response.json({error:'Sign in to continue.'},{status:401}));
  await assert.rejects(academyRequest('classroom'),error=>error.status===401&&error.message==='Sign in to continue.');
  globalThis.fetch=async()=>Response.json({error:'Please enter a question.'},{status:400});
  await assert.rejects(academyRequest('questions',{body:''}),error=>error.status===400&&error.message==='Please enter a question.'&&!error.requestUncertain);
});

test('server and proxy failure details stay behind the scenes',async t=>{
  t.mock.method(globalThis,'fetch',async()=>Response.json({error:'Internal database connection path and provider configuration'},{status:500}));
  await assert.rejects(academyRequest('classroom'),error=>error.status===500&&!error.message.includes('database'));
  await assert.rejects(academyRequest('progress',{lesson:0,complete:true}),error=>error.requestUncertain&&error.message.includes('confirm')&&!error.message.includes('database'));
  globalThis.fetch=async()=>({ok:false,status:502,json:async()=>{throw new SyntaxError('Unexpected token < in HTML proxy page')}});
  await assert.rejects(academyRequest('classroom'),error=>!error.message.includes('Syntax')&&!error.message.includes('HTML')&&error.message.includes('connect'));
});
