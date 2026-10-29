const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const html=fs.readFileSync(require('node:path').join(__dirname,'../protrader_mobile.html'),'utf8');
const NOW=1800000450;
function section(from,to){const start=html.indexOf(from),end=html.indexOf(to,start);assert.ok(start>=0&&end>start,from);return html.slice(start,end);}
function model({score=7,unknown=0,dir='buy',blocked=null,entry=true}={}){
  const available=unknown===0&&dir!=='neutral';
  return {gates:{dir,score,total:10,unavailable:unknown,available,percentage:available?Math.round(score/10*100):null,
    gates:Array.from({length:10},(_,i)=>({name:'gate'+i,detail:i<score?'Matches':i<score+unknown?'Unavailable':'Does not match',pass:i<score?true:i<score+unknown?null:false}))},
    verdict:{v:blocked==='BLOCKED'?'BLOCKED':blocked?'OBSERVER':available?'MATCHED':'UNAVAILABLE',msg:blocked?'Fixture blocking condition applies':'Checklist match; review concerns'},
    entry:entry?{entry:1.1,slLevel:1.09,tp1:1.115,tp2:1.12,tp3:1.14,lotSize:'Fixture paper risk'}:null,
    mcc:{code:blocked&&blocked!=='BLOCKED'?blocked:'TREND',label:'Trend',desc:'Fixture context'},
    session:{label:'London'},wyck:{phase:'MARKUP',desc:'Fixture context'},patternAlign:'',
    dataStatus:{available:true,forming:true,time:NOW-450,message:'Forming candle · score can change'}};
}
function harness(initial=model(),packet=null){
  const panel={innerHTML:''},ariaPanel={innerHTML:''},calls=[];
  const button={setAttribute(){},focus(){},scrollIntoView(){},textContent:''};let current=initial;
  const context=vm.createContext({document:{activeElement:null,getElementById:id=>({
    'check-panel':panel,'aria-panel':ariaPanel,chkMoreToggle:button,chkMore:{classList:{toggle(){}}}
  }[id])},S:{dp:5,sym:'EURUSD',symLabel:'EUR/USD',tf:'15m',balance:10000,riskPct:1,newsWeek:false,candles:[]},
    window:{OracleAnalyst:{getPacket:()=>packet,open:()=>calls.push('oracle-open'),send:()=>{throw Error('Opening Oracle must not send a question');}}},
    CHECK_TERMS:{},AM:{totalSig:0,wins:0},pairPrices:{},getSession:()=>({label:'London',col:'blue',desc:'Fixture session'}),
    otMoney:n=>n.toFixed(2),riskLots:()=>({lots:.1,min:.01}),checkModel:()=>current,
    setRTab:tab=>calls.push(['tab',tab]),applyARIA:(...args)=>calls.push(['apply',...args]),
    OT:{setStage:stage=>calls.push(['stage',stage]),sizeToRisk:value=>calls.push(['size',value]),submit:()=>{throw Error('No order may be submitted');}},
    isMobile:()=>false,openMobilePanel:panel=>calls.push(['mobile',panel])});
  vm.runInContext(section('const ARIA_GATE_COUNT =','function ariaMCC('),context);
  vm.runInContext(section('const CHECK_UI','function openTerm('),context);
  vm.runInContext(section('function renderARIA()','function applyARIA('),context);
  return{context,panel,ariaPanel,calls,setModel:next=>{current=next;}};
}

test('check displays70 percent beside7of10 and expands to all ten conditions across repeated renders',()=>{
  const h=harness();h.context.renderCheck();
  assert.match(h.panel.innerHTML,/70<small>%<\/small>/);assert.match(h.panel.innerHTML,/7 of 10 conditions met/);
  assert.match(h.panel.innerHTML,/ARIA checklist match/);assert.match(h.panel.innerHTML,/Checklist completion, not the probability of a winning trade/);
  assert.match(h.panel.innerHTML,/Forming candle · score can change/);assert.match(h.panel.innerHTML,/Journal · Review my idea/);
  assert.match(h.panel.innerHTML,/See all 10 checks/);
  assert.ok(h.panel.innerHTML.indexOf('id="chkMoreToggle"')<h.panel.innerHTML.indexOf('id="chkOracle"'),'Check the ten conditions before seeking another view');
  assert.equal((h.panel.innerHTML.match(/onclick="openTerm\('/g)||[]).length,10,'The breakdown must expose all ten rules');
  assert.match(h.panel.innerHTML,/aria-expanded="false"/);assert.doesNotMatch(h.panel.innerHTML,/EXECUTION READY|size normally|confidence/i);
  h.context.toggleMoreChecks();for(let i=0;i<10;i++)h.context.renderCheck();
  assert.match(h.panel.innerHTML,/class="chk-more open"/);assert.match(h.panel.innerHTML,/aria-expanded="true"/);
  h.context.toggleMoreChecks();h.context.renderCheck();assert.match(h.panel.innerHTML,/aria-expanded="false"/);
  h.context.showCheckBreakdown();assert.match(h.panel.innerHTML,/class="chk-more open"/);
});

test('reading and key concerns precede a stable ten-rule breakdown as results change',()=>{
  const h=harness();h.context.renderCheck();
  assert.ok(h.panel.innerHTML.indexOf('chk-reading')<h.panel.innerHTML.indexOf('chk-score-card'));
  assert.ok(h.panel.innerHTML.indexOf('chk-concerns')<h.panel.innerHTML.indexOf('id="chkRule0"'));
  assert.doesNotMatch(h.panel.innerHTML,/chk-oracle|Explain this score|Lesson \d/);
  h.context.toggleMoreChecks();
  const changed=model();changed.gates.gates[0].pass=false;changed.gates.gates[9].pass=true;h.setModel(changed);h.context.renderCheck();
  for(let i=0;i<9;i++)assert.ok(h.panel.innerHTML.indexOf(`id="chkRule${i}"`)<h.panel.innerHTML.indexOf(`id="chkRule${i+1}"`));
  assert.match(h.panel.innerHTML,/class="chk-more open"/);
});

test('tick refresh restores a focused explanation control without scrolling the panel',()=>{
  const h=harness();h.context.renderCheck();
  const button={id:'chkRule7',focus:options=>{assert.equal(options.preventScroll,true);h.context.document.activeElement=button;}};
  const original=h.context.document.getElementById;h.context.document.getElementById=id=>id==='chkRule7'?button:original(id);
  h.panel.contains=element=>element===button;h.panel.scrollTop=37;
  let content=h.panel.innerHTML;Object.defineProperty(h.panel,'innerHTML',{get:()=>content,set:value=>{content=value;h.context.document.activeElement=null;}});
  h.context.document.activeElement=button;h.setModel(model({score:8}));h.context.renderCheck();
  assert.equal(h.context.document.activeElement,button);assert.equal(h.panel.scrollTop,37);
});

test('desktop count examples retain the same ten-rule denominator in Check and ARIA details',()=>{
  for(const [score,percentage] of [[5,50],[7,70],[8,80],[10,100]]){
    const h=harness(model({score}));h.context.renderARIA();
    for(const view of [h.panel.innerHTML,h.ariaPanel.innerHTML]){
      assert.ok(view.includes(percentage+'<small>%</small>')||view.includes(percentage+'%'),`${score} rules should be ${percentage}%`);
      assert.ok(view.includes(score+' of 10')||view.includes(score+'/10'),`${score} of ten remains visible`);
      assert.doesNotMatch(view,/of 9|\/9 conditions/);
    }
    assert.equal(h.context.AM.totalSig,0);assert.deepEqual(h.calls,[]);
  }
});

test('unknown checks withhold the percentage and trade handoff without shrinking the denominator',()=>{
  const h=harness(model({score:7,unknown:1,entry:false}));h.context.renderCheck();h.context.reviewFromCheck();
  assert.match(h.panel.innerHTML,/data-available="false"/);assert.match(h.panel.innerHTML,/chk-score-value">—/);
  assert.match(h.panel.innerHTML,/7 of 10 conditions met · 1 unavailable/);assert.match(h.panel.innerHTML,/percentage is withheld/);
  assert.doesNotMatch(h.panel.innerHTML,/<small>%<\/small>|onclick="reviewFromCheck\(\)"/);assert.deepEqual(h.calls,[]);
});

test('neutral evidence never appears as a sell candidate or exposes trade levels',()=>{
  const h=harness(model({score:1,unknown:7,dir:'neutral',entry:false}));h.context.renderCheck();h.context.reviewFromCheck();
  assert.match(h.panel.innerHTML,/No clear direction/);assert.match(h.panel.innerHTML,/>Neutral</);
  assert.doesNotMatch(h.panel.innerHTML,/SELL candidate|Illustrative entry|onclick="reviewFromCheck\(\)"|<small>%<\/small>/);
  assert.deepEqual(h.calls,[]);
});

test('a100percent checklist keeps every hard block above the score and prevents direct handoff',()=>{
  for(const blocked of ['BLOCKED','DEAD_ZONE','FAKE_BREAK']){
    const h=harness(model({score:10,blocked}));h.context.renderCheck();h.context.reviewFromCheck();
    assert.match(h.panel.innerHTML,/100<small>%<\/small>/);assert.match(h.panel.innerHTML,/Check paused/);
    assert.ok(h.panel.innerHTML.indexOf('chk-alert')<h.panel.innerHTML.indexOf('<section class="chk-score-card"'));
    assert.match(h.panel.innerHTML,/high match does not override/);assert.doesNotMatch(h.panel.innerHTML,/onclick="reviewFromCheck\(\)"/);
    assert.deepEqual(h.calls,[]);
  }
});

test('missing model, stale evidence and null entry block direct handoff as well as its button',()=>{
  for(const m of [null,{unavailableReason:'Candle data is stale; refresh the market',dataStatus:{available:false}},model({score:8,entry:false})]){
    const h=harness(m);h.context.renderCheck();h.context.reviewFromCheck();
    assert.doesNotMatch(h.panel.innerHTML,/onclick="reviewFromCheck\(\)"/);assert.deepEqual(h.calls,[]);
    if(!m||m.unavailableReason)assert.doesNotMatch(h.panel.innerHTML,/<small>%<\/small>/);
  }
  const h=harness();h.context.reviewFromCheck();
  assert.deepEqual(h.calls,[['apply',1.09,1.12,'buy'],['stage','before'],['size',true]]);
});

test('ARIA details handle incomplete and blocked plans without null-level crashes or signal generation',()=>{
  for(const m of [model({unknown:1,entry:false}),model({score:1,unknown:7,dir:'neutral',entry:false}),model({score:10,blocked:'FAKE_BREAK'})]){
    const h=harness(m);h.context.renderARIA();
    assert.doesNotMatch(h.ariaPanel.innerHTML,/Review levels in trade ticket|Illustrative levels|EXECUTION READY|Sig:|Acc:/);
    assert.equal(h.context.AM.totalSig,0);assert.deepEqual(h.calls,[]);
  }
});

test('Oracle link opens conversation without sending or copying the score into it',()=>{
  const packet={snapshot:{symbol:'EURUSD',asOf:NOW-30},analysis:{timeframe:'15m'}};
  const before=JSON.stringify(packet),h=harness(model(),packet);h.context.renderCheck();
  assert.match(h.panel.innerHTML,/Ask Oracle for another view/);assert.match(h.panel.innerHTML,/onclick="openOracleFromCheck\(\)"/);
  assert.match(h.panel.innerHTML,/saved completed-candle evidence/);assert.match(h.panel.innerHTML,/Refresh there for a new reading/);
  h.context.openOracleFromCheck();assert.deepEqual(h.calls,[['tab','oracle']]);assert.equal(JSON.stringify(packet),before);
  const other=harness(model(),{snapshot:{symbol:'OTHER',asOf:NOW},analysis:{timeframe:'15m'}});other.context.renderCheck();
  assert.match(other.panel.innerHTML,/Oracle loads its own completed-candle evidence when opened/);assert.doesNotMatch(other.panel.innerHTML,/Oracle uses saved completed-candle evidence/);
});

test('fresh plausible bars without matching provider provenance cannot produce a score or handoff',()=>{
  const DateAtCutoff=class extends Date{static now(){return NOW*1000;}};
  const candles=Array.from({length:201},(_,i)=>({time:NOW-450-(200-i)*900,open:100,high:102,low:99,close:101}));
  const context=vm.createContext({Date:DateAtCutoff,S:{sym:'FIXTURE',tf:'15m',candles},TF_SEC:{'15m':900},
    calcEMA:()=>{throw Error('Unknown provenance must stop before indicator computation');}});
  vm.runInContext(section('function ariaValidCandle(','function ariaGates(')+section('function ariaLiveDataStatus(','function riskLots('),context);
  assert.equal(context.ariaLiveDataStatus(candles,'15m',NOW).available,true,'Shape and freshness alone cannot establish provenance');
  for(const provenance of [undefined,null,
    {symbol:'OTHER',timeframe:'15m',source:'Deriv'},
    {symbol:'FIXTURE',timeframe:'1h',source:'Deriv'},
    {symbol:'FIXTURE',timeframe:'15m',source:'sim'},
    {symbol:'FIXTURE',timeframe:'15m'}]){
    context.S.candleProvenance=provenance;
    const result=context.checkModel();assert.ok(result.unavailableReason);assert.equal(result.gates,undefined);
    const h=harness(result);h.context.renderCheck();h.context.reviewFromCheck();
    assert.doesNotMatch(h.panel.innerHTML,/<small>%<\/small>|onclick="reviewFromCheck\(\)"/);assert.deepEqual(h.calls,[]);
  }
});

test('actual timing validator separates forming, closed, stale, future and malformed histories',()=>{
  const DateAtCutoff=class extends Date{static now(){return NOW*1000;}};
  const context=vm.createContext({Date:DateAtCutoff,S:{sym:'FIXTURE',tf:'15m',candleProvenance:{symbol:'FIXTURE',timeframe:'15m',source:'Deriv',observedAt:NOW}},TF_SEC:{'15m':900},calcEMA:()=>{throw Error('Unavailable histories must stop before indicators');}});
  vm.runInContext(section('function ariaValidCandle(','function ariaGates(')+section('function ariaLiveDataStatus(','function riskLots('),context);
  const bars=Array.from({length:30},(_,i)=>({time:NOW-450-(29-i)*900,open:100,high:102,low:99,close:101}));
  const forming=context.ariaLiveDataStatus(bars,'15m',NOW);assert.equal(forming.available,true);assert.equal(forming.forming,true);
  const closed=context.ariaLiveDataStatus(bars,'15m',NOW+450);assert.equal(closed.available,true);assert.equal(closed.forming,false);
  for(const [name,mutate] of [
    ['stale',items=>items.forEach(b=>b.time-=3600)],
    ['future',items=>{items.at(-1).time=NOW+1;}],
    ['unordered',items=>{items.at(-1).time=items.at(-2).time;}],
    ['invalid OHLC',items=>{items.at(-1).low=-1;}]
  ]){
    const items=bars.map(b=>({...b}));mutate(items);assert.equal(context.ariaLiveDataStatus(items,'15m',NOW).available,false,name);
    context.S.candles=items;const result=context.checkModel();assert.equal(result.dataStatus.available,false,name);assert.ok(result.unavailableReason,name);
    const h=harness(result);h.context.renderCheck();h.context.reviewFromCheck();assert.doesNotMatch(h.panel.innerHTML,/<small>%<\/small>/);assert.deepEqual(h.calls,[]);
  }
});

test('Oracle opens the analyst independently from Journal planning',()=>{
  let mounts=0,renders=0;const panel={innerHTML:''};
  const context=vm.createContext({document:{getElementById:()=>panel},
    window:{OracleAnalyst:{},OracleMarket:{}},
    OracleAnalyst:{mount(){mounts++;},render(){renders++;},getPacket:()=>({})},oracleAdapter:()=>({captureSnapshot(){}}),
    ariaGates:()=>{throw Error('Oracle must not ask ARIA for its first opinion');}});
  const start=html.indexOf('function renderOracle()');
  vm.runInContext(html.slice(start,html.indexOf('function openLearningJournal',start)),context);
  context.renderOracle();context.renderOracle();assert.equal(mounts,1);assert.equal(renders,2);
  context.window.OracleAnalyst=null;context.renderOracle();assert.match(panel.innerHTML,/loading/);
});

test('Oracle preserves an unsupported selected chart horizon instead of silently reading 15m',()=>{
  const context=vm.createContext({S:{sym:'R_50',tf:'1d'},PAIR_MAP:{R_50:{label:'Vol 50'}},
    OracleMarket:{HIGHER:{'1m':'15m','5m':'1h','15m':'1h','1h':'4h','4h':'1d'}},
    botOwnsChart:()=>false,derivSym:s=>s,oraclePaperAccount:()=>({}),oraclePaperSpec:()=>null,oracleLessonRef:()=>null});
  const start=html.indexOf('function oracleContext(');
  vm.runInContext(html.slice(start,html.indexOf('function oracleExecution',start)),context);
  const result=context.oracleContext();assert.equal(result.timeframe,'1d');assert.equal(result.supportedTimeframes.includes('1d'),false);
});
