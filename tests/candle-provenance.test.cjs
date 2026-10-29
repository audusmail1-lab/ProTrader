const {test}=require('node:test');
const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const html=fs.readFileSync(path.join(__dirname,'../protrader_mobile.html'),'utf8');
function section(from,to){const start=html.indexOf(from),end=html.indexOf(to,start);assert.ok(start>=0&&end>start,from);return html.slice(start,end);}
function bars(start,count,price=100){return Array.from({length:count},(_,i)=>({time:(start+i)*900,open:price,high:price+2,low:price-1,close:price+1,vol:1}));}
function provenance(source){return {symbol:'FIXTURE',timeframe:'15m',source,observedAt:Date.now()/1000};}
function harness(source='Deriv'){
  const calls=[],S={sym:'FIXTURE',tf:'15m',candles:bars(100,6),candleProvenance:source?provenance(source):null},noop=()=>{};
  const context=vm.createContext({S,TF_SEC:{'15m':900},TF_AGG:{},MAX_HISTORY_BARS:1000,console:{info:noop,warn:noop},fetchDerivHistory:async()=>{calls.push('Deriv');return bars(97,3,300);}});
  vm.runInContext(section('function ariaValidCandle(','function ariaDirection(')+'var CH={'+section('  seriesIsReal() {','  setLoadingBadge(on) {')+'};',context);
  Object.assign(context.CH,{ready:false,history:{loading:false,exhausted:false,tries:0},setLoadingBadge:on=>calls.push(['loading',on]),signature:()=> 'fixture',clean:items=>items,paintSeries:()=>calls.push('paint'),refreshLevels:noop,syncOverlay:noop});
  return {context,calls,S,CH:context.CH};
}
function deferred(){let resolve;const promise=new Promise(done=>{resolve=done;});return {promise,resolve};}
test('current Deriv-only chart backfills only its recorded provider and never infers source from timestamps',async()=>{
  for(const source of [null,'Yahoo','sim','Deriv']){
    const h=harness(source),original=h.S.candleProvenance;await h.CH.loadOlder();
    assert.equal(h.S.candles.length,source==='Deriv'?9:6,source);
    assert.equal(h.calls.includes('Deriv'),source==='Deriv');assert.equal(h.S.candleProvenance,original);
  }
});
test('a pending backfill cannot prepend to another provider or a replacement history',async()=>{
  for(const replacement of ['Deriv','Yahoo',null]){
    const h=harness(),pending=deferred();h.context.fetchDerivHistory=()=>pending.promise;
    const run=h.CH.loadOlder();assert.equal(h.CH.history.loading,true);
    const current=bars(102,4,700);h.S.candles=current;h.S.candleProvenance=replacement?provenance(replacement):null;
    pending.resolve(bars(97,3,200));await run;assert.equal(h.S.candles,current);assert.equal(h.calls.includes('paint'),false);assert.equal(h.CH.history.loading,false);
  }
});
test('backfill revalidates native candle shape after awaiting the provider',async()=>{
  for(const mutate of [h=>h.S.candles.at(-1).time++,h=>h.S.candleProvenance.needsRefresh=true,h=>h.S.candles.at(-1).high=-1]){
    const h=harness(),pending=deferred();h.context.fetchDerivHistory=()=>pending.promise;
    const run=h.CH.loadOlder();mutate(h);pending.resolve(bars(97,3,300));await run;
    assert.equal(h.S.candles.length,6);assert.equal(h.calls.includes('paint'),false);assert.equal(h.CH.history.loading,false);
  }
});
test('backfill drops malformed, out-of-order and wrong-interval bars',async()=>{
  const h=harness();h.context.fetchDerivHistory=async()=>[...bars(97,1),{...bars(98,1)[0],time:98*900+1},{...bars(99,1)[0],low:-2}];
  await h.CH.loadOlder();assert.equal(h.S.candles.length,7);assert.equal(h.S.candles[0].time,97*900);
});
