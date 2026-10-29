const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const html=fs.readFileSync(path.join(__dirname,'../protrader_mobile.html'),'utf8');
function section(a,b){const i=html.indexOf(a),j=html.indexOf(b,i);assert.ok(i>=0&&j>i,a);return html.slice(i,j);}
const NOW=1800000450,noop=()=>{};
function bars(n=220,end=NOW-450){return Array.from({length:n},(_,i)=>({time:end-(n-1-i)*900,open:100,high:102,low:99,close:101,vol:0}));}
function harness(){
 let now=NOW;const calls=[],elements={},S={sym:'R_50',symLabel:'Vol 50',tf:'15m',dp:2,newsWeek:false,balance:10000,riskPct:1,candles:bars(),activePatterns:[],candleProvenance:{symbol:'R_50',timeframe:'15m',source:'Deriv',observedAt:NOW}};
 const c=vm.createContext({S,Date:class extends Date{static now(){return now*1000;}},window:{},TF_SEC:{'15m':900,'5m':300,'1w':604800,'1d':86400},TF_AGG:{},MAX_HISTORY_BARS:1000,tfBase:tf=>tf,
   safeEl:id=>(elements[id]||={dataset:{},className:'',textContent:''}),document:{getElementById:id=>(elements[id]||={innerHTML:''})},normalizeChg:(_id,c)=>c,formatPct:(_id,c)=>String(c),setTimeout:()=>0,clearTimeout:noop,requestChartRedraw:noop,getSession:()=>({label:'Fixture'}),subscribeHistory:id=>calls.push(['history',id]),checkEscape:String});
 vm.runInContext(section('function calcEMA(','let chartOffset = 0;')+section('const ARIA_GATE_COUNT','function renderARIA()')+section('function ariaLiveDataStatus(','/* Lot that loses')+section('function mergeLiveCandle(','/* ════════════════════════════════════════════════════════════\n   TRADING BOT FEED')+section('const PATTERNS =','/* ════════════════════════════════════════════════════════════\n   MTF CONFLUENCE')+section('function updateLiveTickSafe(','// Last real quote'),c);
 return {c,S,calls,elements,setNow:n=>now=n};
}
test('unverified scanner evidence cannot produce any pattern card or ARIA score',()=>{
 const h=harness();h.S.candleProvenance=null;h.c.runPatternScanner();assert.equal(h.S.activePatterns.length,0);assert.match(h.elements.scannerPane.innerHTML,/verified market candle history/);assert.ok(h.c.checkModel().unavailableReason);
});
test('quote updates cannot mutate any provider history or resurrect old bars',()=>{
 for(const source of ['Deriv','Yahoo']){
  const h=harness();h.S.candleProvenance.source=source;h.S.candles=bars(220,NOW-86400-450);const original=JSON.stringify(h.S.candles),observed=h.S.candleProvenance.observedAt;
  h.c.updateLiveTickSafe(500,2,'Deriv');assert.equal(JSON.stringify(h.S.candles),original);assert.equal(h.S.candleProvenance.observedAt,observed);assert.ok(h.c.checkModel().unavailableReason);assert.equal(h.elements.livePrice.textContent,'500.00');
 }
});
test('only matching OHLC updates affect the chart, and a gap requires history refresh',()=>{
 const h=harness(),before=JSON.stringify(h.S.candles),bar={...h.S.candles.at(-1),high:103,close:102};
 assert.equal(h.c.mergeLiveCandle(bar,'Yahoo'),false);assert.equal(JSON.stringify(h.S.candles),before);
 assert.equal(h.c.mergeLiveCandle(bar,'Deriv'),true);assert.equal(h.S.candles.at(-1).close,102);
 h.setNow(NOW+3600);assert.equal(h.c.mergeLiveCandle({...bar,time:bar.time+3600}),false);assert.equal(h.S.candleProvenance.needsRefresh,true);assert.deepEqual(h.calls,[['history','R_50']]);assert.ok(h.c.checkModel().unavailableReason);
});
test('wall-clock passage cannot falsely finalize a saved forming candle',()=>{
 const h=harness();assert.equal(h.c.ariaHistoryStatus().forming,true);
 h.setNow(NOW+450);assert.equal(h.c.ariaHistoryStatus().available,false);assert.match(h.c.ariaHistoryStatus().message,/provider.*confirm/);
 h.S.candleProvenance.observedAt=NOW+450;assert.equal(h.c.ariaHistoryStatus().available,true);assert.equal(h.c.ariaHistoryStatus().forming,false);
});
test('flat prices yield neutral RSI; mislabeled 15m history cannot become 5m',()=>{
 const h=harness();assert.equal(h.c.calcRSI(Array(220).fill(100)).at(-1),50);
 assert.equal(h.c.ariaLiveDataStatus(h.S.candles,'5m',NOW).available,false);
});
function socketHarness(){
 const sent=[],sockets=[],S={sym:'R_50',tf:'15m',candles:[],activePatterns:[],wsConnected:true};let req=1000000;
 class WS{static OPEN=1;static CONNECTING=0;constructor(){this.readyState=1;sockets.push(this);}close(){}}
 const c=vm.createContext({S,TF_SEC:{'15m':900,'5m':300},tfBase:tf=>tf,WebSocket:WS,DERIV_WS_URL:'fixture',NEXUS:{activeSubs:new Map(),errors:new Map()},FEEDX:{route:()=>false,reset:noop},FEEDQ:{ack:noop,reset:noop},XQ:{q:{},put:noop},setTimeout:()=>0,clearInterval:noop,setInterval:()=>0,derivSym:s=>s,appSym:s=>s,aggregateCandles:a=>a,putQuote:noop,drawChart:noop,renderARIA:noop,renderMTF:noop,runPatternScanner:noop,updateTopbar:noop,setWsBadge:noop,updateFeedBadge:noop,safeEl:()=>null,mergeLiveCandle:()=>{throw Error('Unexpected OHLC');},subscribeTick:noop,
 sendWS:(payload,_priority,opts)=>{const p={...payload};if(p.ticks_history){p.req_id=++req;opts.onSent({payload:p});}sent.push({payload:p,opts});}});
 vm.runInContext('let ws=null,wsRetry=0,_histSubId=null;'+section('let _histGran =','// The chart says when')+section('connectWS=function()', '\nselectPair=function')+';globalThis.getSubscription=()=>_histSubId;globalThis.getWS=()=>ws;',c);
 c.connectWS();return {c,S,sent,ws:sockets[0],reply:(reqId,symbol,tf,id)=>sockets[0].onmessage({data:JSON.stringify({msg_type:'candles',req_id:reqId,echo_req:{ticks_history:symbol,granularity:tf},subscription:{id},candles:[{epoch:1800000000,open:100,high:102,low:99,close:101}]})})};
}
test('chart switch forgets its prior stream and rejects late subscriptions even on A-B-A',()=>{
 const h=socketHarness();h.c.subscribeHistory('R_50');const a=h.sent.at(-1).payload.req_id;h.reply(a,'R_50',900,'A1');assert.equal(h.c.getSubscription(),'A1');
 h.S.sym='R_25';h.c.subscribeHistory('R_25');assert.ok(h.sent.some(x=>x.payload.forget==='A1'));const b=h.sent.at(-1).payload.req_id;
 h.S.sym='R_50';h.c.subscribeHistory('R_50');const newer=h.sent.at(-1).payload.req_id;const before=h.S.candles;
 h.reply(a,'R_50',900,'A-late');assert.equal(h.S.candles,before);assert.ok(h.sent.some(x=>x.payload.forget==='A-late'));
 h.reply(b,'R_25',900,'B-late');assert.equal(h.S.candles,before);assert.ok(h.sent.some(x=>x.payload.forget==='B-late'));
 h.reply(newer,'R_50',900,'A2');assert.equal(h.c.getSubscription(),'A2');assert.equal(h.S.candleProvenance.source,'Deriv');
 h.ws.onclose();assert.equal(h.c.getSubscription(),null);assert.equal(h.S.candleProvenance.needsRefresh,true);assert.equal(h.c.NEXUS.activeSubs.size,0);
});
test('explanation dialog Escape restores the initiating control and traps Tab',()=>{
 const listeners={},state={open:false,focus:null},origin={isConnected:true,focus(){state.focus='origin';}},button={focus(){state.focus='close';}},link={focus(){state.focus='link';}},modal={classList:{add(){state.open=true;},remove(){state.open=false;},contains(){return state.open;}},querySelectorAll:()=>[button,link]};
 const els={termModal:modal,termClose:button,termTitle:{},termBody:{},termFoot:{}};
 const c=vm.createContext({window:{addEventListener:(k,f)=>listeners[k]=f},document:{activeElement:origin,getElementById:id=>els[id]},CHECK_TERMS:{fixture:{t:'Title',b:'Meaning',l:2}},CHECK_LESSON_URL:null});
 vm.runInContext(section('let termReturnFocus=', '/* ── account chip'),c);c.openTerm('fixture');assert.equal(state.open,true);assert.equal(state.focus,'close');
 c.document.activeElement=link;listeners.keydown({key:'Tab',preventDefault:noop});assert.equal(state.focus,'close');
 let stopped=false;listeners.keydown({key:'Escape',preventDefault:noop,stopImmediatePropagation(){stopped=true;}});assert.equal(stopped,true);assert.equal(state.open,false);assert.equal(state.focus,'origin');
});
test('mobile Oracle always opens an independent review and never fills trade levels',()=>{
 const source=section('  insights: {','  // "Plan trade":');assert.doesNotMatch(source,/m\.oracle|oracleReasons|Use signal|applyARIA/);assert.match(source,/packet\.marketReview/);assert.match(source,/openMobilePanel\('oracle'\)/);assert.match(source,/Not win probability/);
});
test('each Oracle/MTF history request uses its own interval on the shared feed budget',async()=>{
 const requested=[],asOf=1800000450,TF_SEC={'4h':14400,'1h':3600,'15m':900,'5m':300};
 const c=vm.createContext({AbortController,Date:class extends Date{static now(){return asOf*1000;}},TF_SEC,ProTraderMTF:require('../static/mtf-analysis.js'),MTF:{data:{},frames:new WeakMap()},S:{candles:[{sentinel:true}]},FEEDX:{request:async(p,_time,priority,opts)=>{
   requested.push({p,priority,signal:opts.signal});const seconds=p.granularity,last=Math.floor(asOf/seconds)*seconds;
   return {echo_req:p,candles:Array.from({length:261},(_,i)=>({epoch:last-(260-i)*seconds,open:100+i,high:103+i,low:99+i,close:102+i}))};
 }}});
 vm.runInContext(section('async function fetchMTFRow(','function paintMTF('),c);
 await Promise.all(Object.keys(TF_SEC).map(tf=>c.fetchMTFRow({symbol:'R_50',provider:'Deriv',ticker:'R_50'},tf,new AbortController().signal)));
 assert.deepEqual(requested.map(x=>x.p.granularity),[14400,3600,900,300]);assert.ok(requested.every(x=>x.p.subscribe===undefined&&x.priority===2));
 assert.deepEqual(c.S.candles,[{sentinel:true}]);
 for(const [tf,seconds]of Object.entries(TF_SEC)){const history=c.MTF.data.R_50[tf];assert.ok(history.every(b=>b.time+seconds<=asOf));assert.equal(c.MTF.frames.get(history),tf);}
 c.FEEDX.request=async p=>({echo_req:{...p,granularity:300},candles:[]});await assert.rejects(c.fetchMTFRow({symbol:'R_50',provider:'Deriv',ticker:'R_50'},'1h'),/did not match/);
});
test('cancelled feed-budget requests settle and late replies cannot reenter the chart handler',async()=>{
 const requests=[],timers=new Map();let id=0;
 const c=vm.createContext({setTimeout:fn=>{timers.set(++id,fn);return id;},clearTimeout:i=>timers.delete(i),FEEDQ:{send:(p,_priority,opts)=>{requests.push({p,opts});return true;},ack:noop,refused:()=>false}});
 vm.runInContext(section('const FEEDX =','/* Day open / high / low')+';globalThis.fx=FEEDX;',c);
 const controller=new AbortController(),p=c.fx.request({ticks_history:'R_50'},15000,2,{signal:controller.signal});
 controller.abort();await assert.rejects(p,/cancelled/);assert.equal(requests[0].opts.wanted(),false);assert.equal(timers.size,0);
 assert.equal(c.fx.route({req_id:requests[0].p.req_id,echo_req:{passthrough:{fx:1}},candles:[]}),true);
});
