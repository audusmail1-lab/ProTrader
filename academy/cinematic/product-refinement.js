import {chartSVG,calculatePlan,money,price} from './market-example.js?v=20261002-controls';
const $=s=>document.querySelector(s);
const guide=key=>document.dispatchEvent(new CustomEvent('academy:tool-guide',{detail:key}));
const read=id=>document.dispatchEvent(new CustomEvent('academy:guide',{detail:id}));
const texts={
 aria:['ARIA / CONDITION REVIEW','Read the evidence.<br>Inspect what is missing.','Review the market conditions behind a read, including those that have not matched. Each check should have a reason you can inspect.','Read the ARIA guide'],
 oracle:['ORACLE / SHARED AGREEMENT','One summary.<br>Traceable to its checks.','Oracle summarises the same conditions ARIA explains. Follow the score back to its inputs before drawing a conclusion.','Read the Oracle guide'],
 sentinel:['SENTINEL / MARKET COVERAGE','Multiple markets.<br>Connected timeframes.','A server-side watch across configured markets and timeframes, 24/7. Follow closed-candle context and paper outcomes by model version.','Read the Sentinel guide']
};
function intelligence(){
 const root=$('#intelligence');const heading=root.querySelector('.intelligence-heading').outerHTML;
 const systems=['aria','oracle','sentinel'];
 const icons=[
  '<path class="tool-icon-trace" pathLength="1" d="M4 21V7m0 14h24M7 17l6-6 6 4 7-10"/><circle cx="7" cy="17" r="1.7"/><circle cx="13" cy="11" r="1.7"/><circle cx="19" cy="15" r="1.7"/><circle cx="26" cy="5" r="1.7"/>',
  '<circle class="tool-icon-base" cx="16" cy="16" r="11"/><path class="tool-icon-trace" pathLength="1" d="M16 5a11 11 0 1 1-10.46 7.6"/><circle class="tool-icon-base" cx="16" cy="16" r="5"/><circle cx="16" cy="5" r="1.7"/>',
  '<rect class="tool-icon-base" x="4" y="5" width="24" height="22" rx="3"/><path d="M12 5v22m8-22v22M4 13h24M4 20h24"/><path class="tool-icon-trace" pathLength="1" d="m7 17 2 1 6-9 3 7 6 1"/>'
 ];
 root.innerHTML=heading+`<div class="intelligence-tabs intelligence-rail" role="tablist" aria-label="Intelligence systems" aria-orientation="horizontal">${systems.map((key,i)=>`<button type="button" role="tab" data-tool="${key}" id="tab-${key}" aria-controls="intelligence-panel" aria-selected="${i===0}" tabindex="${i===0?0:-1}"><span class="tool-icon" aria-hidden="true"><svg viewBox="0 0 32 32" fill="none" focusable="false">${icons[i]}</svg></span><span class="tool-label"><b>${key==='aria'?'ARIA':key[0].toUpperCase()+key.slice(1)}</b><small>${['Explain the evidence','Summarise the checks','Monitor the markets'][i]}</small></span><span class="tool-number" aria-hidden="true">0${i+1}</span></button>`).join('')}</div><div class="intelligence-experience pro-experience" id="intelligence-panel" role="tabpanel" aria-labelledby="tab-aria" tabindex="0"><div class="experience-copy" id="experience-copy"></div><div class="experience-demo pro-demo" id="experience-demo"></div></div><div class="intelligence-footer"><p>One shared set of checks. A connected view of your workspace.<br><b>Explore the examples here. Inspect actual reads in the app.</b></p><button class="text-button" id="tools-together">See the connected workflow</button></div>`;
 const rail=root.querySelector('.intelligence-rail');
 let selected='aria',count=8,expanded=false,cell={market:'EUR/USD',tf:'15m'};
 function checks(){return [
  ['EMA structure','EMA 20 > EMA 50','Trend',true],['RSI momentum','RSI 14 · 56.4','Momentum',true],['MACD direction','0.00031 > 0.00024','Momentum',true],['Market structure','Higher high / higher low','Trend',true],['Candle close','Above the prior close','Price context',true],['Volatility','ATR 14 · 0.00072','Volatility',true],['4h alignment',count===8?'Close above EMA 200':'Close below EMA 200','Trend',count===8],['Stochastic',count===8?'%K 62.1 > %D 54.6':'%K 41.2 < %D 47.3','Momentum',count===8],['Recent pattern','No confirmed pattern','Price context',false],['Fibonacci zone','Outside retracement zone','Price context',false]
 ]}
 const selection=()=>`<label class="snapshot-selector">Example snapshot<select id="example-snapshot"><option value="8" ${count===8?'selected':''}>Greater alignment</option><option value="6" ${count===6?'selected':''}>Mixed conditions</option></select></label>`;
 function render(){
  const t=texts[selected];root.querySelectorAll('[data-tool]').forEach(b=>{const on=b.dataset.tool===selected;b.setAttribute('aria-selected',on);b.tabIndex=on?0:-1});rail.style.setProperty('--tool-index',systems.indexOf(selected));$('#intelligence-panel').setAttribute('aria-labelledby','tab-'+selected);
  $('#experience-copy').innerHTML=`<span class="eyebrow">${t[0]}</span><h3>${t[1]}</h3><p>${t[2]}</p><div class="product-definition">${selected==='aria'?'10 defined checks · selected market and timeframe':selected==='oracle'?'Agreement is not a forecast or win probability.':'Closed candles · higher-timeframe context · research outcomes'}</div><button class="dark-button" id="read-tool">${t[3]}</button>`;
  const head=`<div class="pro-window-bar"><b>${selected==='sentinel'?'Coverage monitor':'Analysis / EUR/USD'}</b><span>ILLUSTRATIVE DATA</span></div>`;
  if(selected==='aria')$('#experience-demo').innerHTML=head+`<div class="pro-analysis-context"><span>EUR/USD <b>15m</b><small>Closed-candle example</small></span>${selection()}</div><div class="analysis-verdict"><div><small>SETUP REVIEW</small><strong>Evidence to review</strong></div><span><b>${count} / 10</b> matched</span></div><div class="evidence-table"><div class="evidence-head"><span>Condition</span><span>Observed value</span><span>State</span></div>${checks().map(([name,value,group,ok],i)=>`<div class="evidence-row" ${!expanded&&i>=5?'hidden':''}><b>${name}</b><span>${value}</span><small class="${ok?'state-matched':'state-unmet'}">${ok?'Matched':'Unmet'}</small></div>`).join('')}</div><button class="evidence-expand" aria-expanded="${expanded}" id="more-evidence">${expanded?'Show fewer conditions':'Inspect all 10 conditions'} <svg class="academy-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><use href="/ui-icons.svg#${expanded?'minus':'plus'}"></use></svg></button><p class="pro-footnote" role="status">${10-count} checks remain unmet. Review the missing evidence; agreement alone does not validate a trade.</p>`;
  if(selected==='oracle')$('#experience-demo').innerHTML=head+`
   <div class="pro-analysis-context"><span>ORACLE <b>15m</b><small>Same inputs as ARIA</small></span>${selection()}</div>
   <div class="oracle-allocation">
    <div class="oracle-allocation-ring" role="img" aria-label="${count*10}% condition agreement: ${count} of 10 checks matched">
     <svg viewBox="0 0 200 200" aria-hidden="true"><circle class="allocation-track" cx="100" cy="100" r="88"/><circle class="allocation-value" cx="100" cy="100" r="88" pathLength="100" stroke-dasharray="${count*10} ${100-count*10}"/></svg>
     <div class="allocation-center" aria-hidden="true"><strong>${count*10}<span>%</span></strong><small>CONDITION<br>AGREEMENT</small></div>
    </div>
    <div class="allocation-key"><span class="allocation-eyebrow">THE READ, AT A GLANCE</span><h4>${count} of 10 matched.</h4><p>Follow the summary back <br>to the conditions behind it.</p><dl><div><dt><i class="key-matched" aria-hidden="true"></i>Matched</dt><dd>${count*10}%</dd></div><div><dt><i class="key-unmet" aria-hidden="true"></i>Unmet</dt><dd>${100-count*10}%</dd></div></dl></div>
   </div>
   <div class="agreement-breakdown">${['Trend','Momentum','Price context','Volatility'].map(group=>{const rows=checks().filter(c=>c[2]===group),n=rows.filter(c=>c[3]).length;return `<div><span>${group}</span><b>${n} / ${rows.length}</b><i aria-hidden="true"><em style="width:${n/rows.length*100}%"></em></i></div>`}).join('')}</div>
   <button class="evidence-expand" id="inspect-inputs">Inspect the underlying ARIA checks</button><p class="pro-footnote" role="status">${count*10}% counts matched conditions, not the probability of profit. Oracle summarises ARIA’s inputs; it adds no independent confirmation.</p>`;
  if(selected==='sentinel'){
   const markets=['EUR/USD','GBP/USD','USD/JPY','BTC/USD'];const timeframes=['15m','1h','4h'];const statuses=[['Review','Aligned','Aligned'],['Mixed','Review','Aligned'],['Mixed','Mixed','Downtrend'],['Await close','Review','Aligned']];
   const marketIndex=markets.indexOf(cell.market),status=statuses[marketIndex][timeframes.indexOf(cell.tf)];
   const stateClass=s=>({'Aligned':'aligned','Mixed':'mixed','Review':'review','Downtrend':'direction','Await close':'pending'}[s]);
   const symbols={'Aligned':'✓','Mixed':'±','Review':'·','Downtrend':'↓','Await close':'—'};
   const context=cell.tf==='4h'?'Review the broader structure at its own candle close. This is the reference timeframe for this example.':`Read the ${cell.tf==='15m'?'15-minute entry context':'hourly structure'} alongside the last closed four-hour trend.`;
   const explanation=status==='Await close'?'The current candle is still forming. Wait for its close before treating it as a new read.':status==='Mixed'?'Conditions differ across this view. Keep the disagreement visible before planning a trade.':status==='Downtrend'?'The broader direction is down in this example. Direction describes context; it is not an instruction to trade.':status==='Review'?'A closed-candle read is ready to inspect. Review the evidence and the missing conditions.':'The example conditions align in this view. Alignment remains evidence to inspect, not a trade instruction.';
   $('#experience-demo').innerHTML=head+`
    <div class="sentinel-overview"><div><span class="allocation-eyebrow">SENTINEL / CONTINUOUS COVERAGE</span><h4>One watch.<br>Many perspectives.</h4></div><div class="sentinel-service"><b>24/7</b><small>SERVER MONITORING</small></div></div>
    <div class="sentinel-markets"><div class="coverage-label"><span>4 markets · 3 timeframes</span><span>15m / 1h / 4h</span></div><div class="market-views" role="group" aria-label="Example market coverage">${markets.map((market,i)=>`<button type="button" data-market="${market}" aria-pressed="${cell.market===market}" aria-label="Inspect ${market}: ${timeframes.map((tf,j)=>`${tf} ${statuses[i][j]}`).join(', ')}"><b>${market}</b><span class="market-status-strip" aria-hidden="true">${statuses[i].map(s=>`<i class="coverage-${stateClass(s)}">${symbols[s]}</i>`).join('')}</span></button>`).join('')}</div></div>
    <div class="sentinel-focus"><div class="sentinel-focus-heading"><b>${cell.market}</b><span>EXPLORE A TIMEFRAME</span></div><div class="timeframe-views" role="group" aria-label="Example timeframe">${timeframes.map((tf,j)=>`<button type="button" data-timeframe="${tf}" aria-pressed="${cell.tf===tf}" aria-controls="sentinel-read" aria-label="${tf}: ${statuses[marketIndex][j]}"><b>${tf}</b><span class="coverage-${stateClass(statuses[marketIndex][j])}">${statuses[marketIndex][j]}</span></button>`).join('')}</div>
    <div id="sentinel-read" class="sentinel-insight" role="status" aria-live="polite" aria-atomic="true"><div class="sentinel-read-title"><span>${cell.tf==='4h'?'BROADER STRUCTURE':cell.tf==='1h'?'LOCAL STRUCTURE':'ENTRY CONTEXT'}</span><b class="coverage-${stateClass(status)}">${status}</b></div><p>${explanation}</p><small>${context}</small></div>
    <div class="sentinel-process" aria-label="Sentinel review workflow"><span>Closed candles</span><i class="workflow-separator" aria-hidden="true"></i><span>Model checks</span><i class="workflow-separator" aria-hidden="true"></i><span>Paper outcomes</span></div></div>
    <p class="pro-footnote">Illustrative coverage, not a live scan. All configured views stay in scope; each cycle checks them in sequence. Market hours and feed availability affect updates. Paper outcomes stay linked to their model version; no broker orders are placed.</p>`;
   root.querySelectorAll('[data-market]').forEach(b=>b.onclick=()=>{cell.market=b.dataset.market;render();root.querySelector(`[data-market="${cell.market}"]`).focus({preventScroll:true})});
   root.querySelectorAll('[data-timeframe]').forEach(b=>b.onclick=()=>{cell.tf=b.dataset.timeframe;render();root.querySelector(`[data-timeframe="${cell.tf}"]`).focus({preventScroll:true})});
  }
  $('#read-tool').onclick=()=>guide(selected);
  $('#example-snapshot')?.addEventListener('change',e=>{count=+e.target.value;render();$('#example-snapshot').focus({preventScroll:true})});
  $('#more-evidence')?.addEventListener('click',()=>{expanded=!expanded;render();$('#more-evidence').focus({preventScroll:true})});
  $('#inspect-inputs')?.addEventListener('click',()=>{expanded=true;selectTool('aria');$('#tab-aria').focus({preventScroll:true})});
 }
 function selectTool(key){
  if(selected===key)return;
  rail.dataset.engaged='true';selected=key;render();
  if(innerWidth<=600){
   const panel=$('#intelligence-panel'),top=panel.getBoundingClientRect().top;
   if(top<175||top>innerHeight-200)panel.scrollIntoView({block:'start',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches||document.documentElement.classList.contains('motion-paused')?'instant':'smooth'});
  }
  if(!matchMedia('(prefers-reduced-motion: reduce)').matches&&!document.documentElement.classList.contains('motion-paused')){
   for(const id of ['#experience-copy','#experience-demo']){
    const panel=$(id);panel.getAnimations().forEach(a=>a.cancel());
    panel.animate([{opacity:.45,transform:'translateY(5px)'},{opacity:1,transform:'translateY(0)'}],{duration:260,easing:'cubic-bezier(.2,.7,.2,1)'});
   }
  }
 }
 root.querySelectorAll('[data-tool]').forEach((b,i)=>{b.onclick=()=>selectTool(b.dataset.tool);b.onkeydown=e=>{let n=i;if(e.key==='ArrowRight')n=(i+1)%3;else if(e.key==='ArrowLeft')n=(i+2)%3;else if(e.key==='Home')n=0;else if(e.key==='End')n=2;else return;e.preventDefault();selectTool(systems[n]);$('#tab-'+selected).focus({preventScroll:true})}});
 $('#tools-together').onclick=()=>window.openModal('One connected review.','<ol><li><b>ARIA:</b> inspect the conditions and their evidence.</li><li><b>Oracle:</b> summarise those same checks without counting them twice.</li><li><b>Sentinel:</b> monitor configured markets and timeframes and follow paper outcomes.</li><li><b>Your plan:</b> define entry, stop, target and size before acting.</li></ol><p>The tools support a review. They do not guarantee its result.</p>','THE PROTRADER WORKFLOW');
 render();
}
function planner(){
 const section=$('#risk');section.classList.add('professional-risk');
 section.innerHTML=`<div class="planner-heading"><div><span class="eyebrow">02 / GUIDED PAPER PRACTICE</span><h2>Every level.<br><em>One considered plan.</em></h2></div><div><p>Set your size. Move a level. See the relationship between risk and reward change as you shape the plan.</p><button class="text-button" id="risk-guide">Understand risk & position size</button></div></div>
 <div class="planner-terminal planner-studio">
 <div class="pro-window-bar"><b><svg class="planner-mark" viewBox="0 0 24 24" aria-hidden="true"><path d="M3 6h18M3 12h18M3 18h18"/><path d="M8 3v6m8 0v6m-6 0v6"/></svg>Position planner</b><div class="planner-window-actions"><span>PAPER PRACTICE</span><button type="reset" form="plan-form" class="reset-plan" aria-label="Reset plan"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M4 8a6 6 0 1 1 .5 6M4 3v5h5"/></svg>Reset</button></div></div>
 <div class="planner-workspace">
 <form id="plan-form" novalidate>
  <div class="plan-direction" role="group" aria-label="Plan direction"><button type="button" data-side="buy" aria-pressed="true"> Long / Buy</button><button type="button" data-side="sell" aria-pressed="false"> Short / Sell</button></div>
  <div class="plan-volume"><label>Position size <span>lots</span><input name="fixedLots" aria-label="Position size in lots" aria-describedby="plan-sizing-note" type="number" min="0.01" max="100" step="0.01" value="0.48" inputmode="decimal"></label></div>
  <div class="plan-primary-prices"><label class="price-field"><span><i class="level-key entry-key"></i>Entry</span><input name="entry" aria-label="Entry price" type="number" min="0.5" max="2" step="0.00001" value="1.08840" inputmode="decimal"></label><label class="price-field"><span><i class="level-key sl-key"></i>Stop loss</span><input name="stop" aria-label="Stop loss price" type="number" min="0.5" max="2" step="0.00001" value="1.08640" inputmode="decimal"></label><label class="price-field"><span><i class="level-key tp-key"></i>Take profit</span><input name="target" aria-label="Take profit price" type="number" min="0.5" max="2" step="0.00001" value="1.09240" inputmode="decimal"></label></div>
  <p id="plan-sizing-note">Fixed size. Moving SL changes risk, not TP profit.</p>
  <details class="plan-settings" id="plan-settings"><summary>Sizing & costs <span class="disclosure-icon"><svg class="academy-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><use href="/ui-icons.svg#plus"></use></svg></span></summary><div class="plan-settings-body"><label class="sizing-toggle"><input id="auto-size" name="autoSize" type="checkbox" aria-describedby="plan-sizing-note"><span>Auto-size to risk budget</span></label><div class="plan-fields"><label>Account value <span>USD</span><input name="balance" aria-label="Account value in USD" type="number" min="100" max="10000000" step="100" value="10000" inputmode="decimal"></label><label><span id="plan-budget-label">Risk reference</span> <span>%</span><input name="riskPercent" aria-label="Risk reference percent" type="number" min="0.01" max="5" step="0.1" value="1" inputmode="decimal"></label></div><label>Commission per lot <span>USD</span><input name="feePerLot" aria-label="Round-trip commission per lot in USD" type="number" min="0" max="100" step="0.5" value="7" inputmode="decimal"></label><p>Round-trip commission. 100,000 EUR per lot; 0.01-lot steps. Auto-size rounds down within your budget. Spread, slippage and financing are excluded.</p></div></details>
  <p id="plan-error" class="plan-error" role="status" aria-live="polite"></p>
  <div class="sizing-result"><span><span id="plan-size-label">Fixed size</span><small id="plan-units"></small></span><b id="plan-size"></b></div>
 </form>
 <div class="plan-chart-area"><div class="plan-chart-toolbar"><b>EUR/USD <span>15m</span></b><span>Candles · EMA 20 / 50</span><small>ILLUSTRATIVE DATA</small></div><div class="plan-chart" id="plan-chart"><div id="plan-price-chart"></div><div class="plan-levels" id="plan-levels">${[['target','TP'],['entry','ENTRY'],['stop','SL']].map(([key,label])=>`<button type="button" class="plan-level level-${key}" data-level="${key}" role="slider" aria-label="Adjust ${key==='target'?'take profit':key==='stop'?'stop loss':'entry'} price" aria-orientation="vertical" aria-valuemin="0.5" aria-valuemax="2" aria-valuenow="1"><span class="level-label"><b>${label}</b><strong data-level-amount="${key}"></strong><svg class="academy-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><use href="/ui-icons.svg#grip"></use></svg></span><span class="level-price" data-level-price="${key}"></span></button>`).join('')}<div class="plan-zone plan-profit"></div><div class="plan-zone plan-loss"></div></div><span class="plan-chart-caption">Drag SL or TP · Watch the plan respond</span></div>
 <div class="plan-outcomes" aria-live="polite" aria-atomic="true"><div class="outcome-loss"><span><i aria-hidden="true"></i>Estimated loss at stop</span><b id="plan-loss" class="negative"></b><small id="plan-stop-distance"></small></div><div class="outcome-profit"><span><i aria-hidden="true"></i>Estimated profit at target</span><b id="plan-profit" class="positive"></b><small id="plan-target-distance"></small></div><div class="outcome-ratio"><span>Reward / risk after fees</span><b id="plan-ratio"></b><small id="plan-cost-summary"></small></div></div>
 <div class="plan-calculation"><span><span id="plan-budget-summary">Risk reference</span> <b id="plan-budget"></b></span><span>Notional <b id="plan-notional"></b></span><span>Local calculation · No order placed</span><p id="plan-budget-note" class="plan-budget-note" role="status"></p></div></div>
 </div></div><p class="planner-disclosure">Illustrative EUR/USD prices and contract assumptions. Estimated outcomes exclude spread and slippage. Practise the relationship; actual execution can differ.</p>`;
 const form=$('#plan-form'),plot=$('#plan-chart'),layer=$('#plan-levels');let side='buy',domain={high:1.094,low:1.084},drag=null,lastValid=null;
 const input=name=>form.elements.namedItem(name);
 function values(){return Object.fromEntries(['balance','riskPercent','entry','stop','target','feePerLot','fixedLots'].map(k=>[k,input(k).value===''?NaN:Number(input(k).value)]))}
 const y=p=>(28+(domain.high-p)/(domain.high-domain.low)*336)/400*100;
 const pixelPrice=clientY=>{const r=plot.getBoundingClientRect();return domain.high-((clientY-r.top)/r.height*400-28)/336*(domain.high-domain.low)};
 function chart(){ $('#plan-price-chart').innerHTML=chartSVG({...domain,width:Math.max(300,plot.clientWidth),visibleBars:plot.clientWidth<500?44:76}) }
 const outcomeIds=new Set(['#plan-loss','#plan-profit','#plan-ratio']);
 const canAnimate=()=>!matchMedia('(prefers-reduced-motion: reduce)').matches&&!document.documentElement.classList.contains('motion-paused');
 const setText=(id,value)=>{
  const el=$(id),previous=el.textContent;el.textContent=value;
  if(outcomeIds.has(id)&&previous&&previous!==value&&canAnimate()){
   el.parentElement.getAnimations().forEach(a=>a.cancel());
   el.parentElement.animate([{backgroundColor:'#bdd2a82c'},{backgroundColor:'transparent'}],{duration:380,easing:'ease-out'});
  }
 };
 function paint(){
  const auto=$('#auto-size').checked,sizingMode=auto?'auto':'fixed';
  input('fixedLots').disabled=auto;
  setText('#plan-sizing-note',auto?'Auto-size on. Moving SL recalculates size and TP profit.':'Fixed size. Moving SL changes risk, not TP profit.');
  setText('#plan-budget-label',auto?'Risk budget':'Risk reference');
  setText('#plan-budget-summary',auto?'Risk budget':'Risk reference');
  setText('#plan-size-label',auto?'Auto-sized':'Fixed size');
  section.dataset.sizing=auto?'auto':'fixed';
  input('riskPercent').setAttribute('aria-label',auto?'Risk budget percent':'Risk reference percent');
  const v=values(),r=calculatePlan({side,sizingMode,...v});
  setText('#plan-budget-note','');
  for(const name of Object.keys(v))input(name).setAttribute('aria-invalid',String(Boolean(r.errors[name])));
  const message=Object.values(r.errors)[0]||(r.belowMinimum?'This risk budget is below the minimum 0.01-lot size. Increase the budget or reduce the planned stop distance.':'');
  setText('#plan-error',message);layer.hidden=!r.valid||r.belowMinimum;
  if(['balance','riskPercent','feePerLot'].some(key=>r.errors[key]))$('#plan-settings').open=true;
  if(!r.valid||r.belowMinimum){for(const id of ['#plan-size','#plan-loss','#plan-profit','#plan-ratio','#plan-budget','#plan-notional'])setText(id,'—');for(const id of ['#plan-units','#plan-stop-distance','#plan-target-distance','#plan-cost-summary'])setText(id,'');return}
  if(auto){input('fixedLots').value=r.lots.toFixed(2);v.fixedLots=r.lots}
  lastValid={...v};
  if(!auto&&r.overBudget)setText('#plan-budget-note','Estimated stop loss is '+money(r.risk-r.budget)+' above your risk reference. Position size stays fixed.');
  if(!drag&&(Math.max(v.entry,v.stop,v.target)>domain.high-.0003||Math.min(v.entry,v.stop,v.target)<domain.low+.0003)){const max=Math.max(v.entry,v.stop,v.target,1.0884),min=Math.min(v.entry,v.stop,v.target,1.085);const pad=Math.max(.001,(max-min)*.15);domain={high:max+pad,low:min-pad};chart()}
  setText('#plan-size',r.lots.toFixed(2)+' lots');setText('#plan-units',r.units.toLocaleString('en-US')+' EUR units');setText('#plan-loss','−'+money(r.risk));setText('#plan-profit',(r.reward<0?'−':'+')+money(Math.abs(r.reward)));$('#plan-profit').className=r.reward<0?'negative':'positive';setText('#plan-ratio',r.ratio.toFixed(2)+' : 1');setText('#plan-stop-distance',r.stopPips.toFixed(1)+' pips from entry');setText('#plan-target-distance',r.targetPips.toFixed(1)+' pips from entry');setText('#plan-cost-summary',money(r.costs)+' assumed commission');setText('#plan-budget',money(r.budget)+' / '+v.riskPercent+'%');setText('#plan-notional',money(r.notional));
  for(const key of ['entry','stop','target']){const h=layer.querySelector(`[data-level="${key}"]`);h.style.top=y(v[key])+'%';h.setAttribute('aria-valuenow',price(v[key]));h.setAttribute('aria-valuetext',price(v[key]));layer.querySelector(`[data-level-price="${key}"]`).textContent=price(v[key]);layer.querySelector(`[data-level-amount="${key}"]`).textContent=key==='entry'?(side==='buy'?'BUY':'SELL')+' '+r.lots.toFixed(2):key==='stop'?'−'+money(r.risk):(r.reward<0?'−':'+')+money(Math.abs(r.reward))}
  for(const [klass,other] of [['.plan-profit','target'],['.plan-loss','stop']]){const el=layer.querySelector(klass);el.style.top=Math.min(y(v.entry),y(v[other]))+'%';el.style.height=Math.abs(y(v.entry)-y(v[other]))+'%'}
 }
 function setLevel(key,value){if(!lastValid)return;const v=lastValid;value=Math.max(domain.low+.00025,Math.min(domain.high-.00025,value));if(key==='stop')value=side==='buy'?Math.min(v.entry-.0001,value):Math.max(v.entry+.0001,value);if(key==='target')value=side==='buy'?Math.max(v.entry+.0001,value):Math.min(v.entry-.0001,value);if(key==='entry'){const delta=value-v.entry;input('stop').value=price(v.stop+delta);input('target').value=price(v.target+delta)}input(key).value=price(value);paint()}
 form.addEventListener('submit',e=>e.preventDefault());form.addEventListener('input',paint);form.addEventListener('reset',e=>{e.preventDefault();form.querySelectorAll('input').forEach(field=>{if(field.type==='checkbox')field.checked=field.defaultChecked;else field.value=field.defaultValue});side='buy';domain={high:1.094,low:1.084};syncSide();chart();paint()});
 function syncSide(){form.querySelectorAll('[data-side]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.side===side)))}
 form.querySelectorAll('[data-side]').forEach(b=>b.onclick=()=>{if(side===b.dataset.side)return;const v=values();side=b.dataset.side;if([v.entry,v.stop,v.target].every(Number.isFinite)){input('stop').value=price(v.entry+(side==='buy'?-1:1)*Math.max(.0001,Math.abs(v.entry-v.stop)));input('target').value=price(v.entry+(side==='buy'?1:-1)*Math.max(.0001,Math.abs(v.target-v.entry)))}syncSide();paint()});
 layer.querySelectorAll('[data-level]').forEach(h=>{
  h.addEventListener('pointerdown',e=>{if(!lastValid||layer.hidden)return;e.preventDefault();h.focus({preventScroll:true});h.setPointerCapture(e.pointerId);drag={key:h.dataset.level,start:e.clientY,price:lastValid[h.dataset.level]};plot.classList.add('dragging');section.dataset.adjusting=h.dataset.level});
  h.addEventListener('pointermove',e=>{if(!drag||drag.key!==h.dataset.level)return;setLevel(drag.key,drag.price+pixelPrice(e.clientY)-pixelPrice(drag.start))});
  const finish=()=>{drag=null;plot.classList.remove('dragging');delete section.dataset.adjusting;paint()};h.addEventListener('pointerup',finish);h.addEventListener('pointercancel',finish);h.addEventListener('lostpointercapture',finish);
  h.addEventListener('keydown',e=>{if(!['ArrowUp','ArrowDown','ArrowLeft','ArrowRight'].includes(e.key)||!lastValid)return;e.preventDefault();setLevel(h.dataset.level,lastValid[h.dataset.level]+(['ArrowUp','ArrowRight'].includes(e.key)?1:-1)*.0001*(e.shiftKey?10:1))});
 });
 $('#risk-guide').onclick=()=>read(0);chart();paint();new ResizeObserver(chart).observe(plot);
}
function review(){
 const paper=$('.review-paper');paper.classList.add('review-ledger');
 paper.innerHTML=`<div class="pro-window-bar"><b>Process journal</b><span>EXAMPLE RECORD / 001</span></div><div class="journal-record"><div><b>EUR/USD</b><span>Long · Paper plan</span></div><small>REVIEW NOTE</small></div><div class="journal-tabs" role="tablist" aria-label="Example journal sections"><button role="tab" aria-selected="true" id="journal-context" aria-controls="journal-detail" data-journal="context">Context</button><button role="tab" tabindex="-1" aria-selected="false" id="journal-plan" aria-controls="journal-detail" data-journal="plan">Plan</button><button role="tab" tabindex="-1" aria-selected="false" id="journal-review" aria-controls="journal-detail" data-journal="review">Reflection</button></div><div id="journal-detail" role="tabpanel" aria-labelledby="journal-context" tabindex="0"></div><div class="journal-bottom">A sample learning record. No personal trading history.</div>`;
 const data={context:'<span class="journal-label">MARKET CONTEXT</span><h3>Higher-timeframe trend.<br>Lower-timeframe structure.</h3><p>The four-hour example is aligned. On the 15-minute chart, identify the level that would invalidate the idea before planning an entry.</p><div class="journal-tags"><span>Structure</span><span>4h / 15m</span><span>Paper practice</span></div>',plan:'<span class="journal-label">THE ORIGINAL PLAN</span><dl class="journal-plan-list"><div><dt>Entry</dt><dd>1.08840</dd></div><div><dt>Stop loss</dt><dd>1.08640</dd></div><div><dt>Take profit</dt><dd>1.09240</dd></div><div><dt>Risk budget</dt><dd>1.0% / $100</dd></div></dl><p>Keep the initial plan so a later result can be reviewed against the original reasoning.</p>',review:'<span class="journal-label">REFLECTION PROMPT</span><h3>Was the process followed?</h3><p>Record any change to the planned stop, size or exit. Separate the market outcome from decisions made during the trade.</p><blockquote>What evidence would change my next decision?</blockquote>'};
 function show(key){$('#journal-detail').innerHTML=data[key];$('#journal-detail').setAttribute('aria-labelledby','journal-'+key);paper.querySelectorAll('[data-journal]').forEach(b=>{const on=b.dataset.journal===key;b.setAttribute('aria-selected',on);b.tabIndex=on?0:-1})}
 const buttons=[...paper.querySelectorAll('[data-journal]')];buttons.forEach((b,i)=>{b.onclick=()=>show(b.dataset.journal);b.onkeydown=e=>{let n=i;if(e.key==='ArrowRight')n=(i+1)%3;else if(e.key==='ArrowLeft')n=(i+2)%3;else if(e.key==='Home')n=0;else if(e.key==='End')n=2;else return;e.preventDefault();show(buttons[n].dataset.journal);buttons[n].focus()}});show('context');
}
export function refineProduct(){document.documentElement.classList.add('professional-interface');intelligence();planner();review()}
