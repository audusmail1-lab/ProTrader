/* Oracle's educational review UI. No order, broker or account mutation APIs. */
(function(root,factory){
  const api=factory(root);
  if(typeof module==='object'&&module.exports)module.exports=api;
  else root.OracleWorkspace=api;
})(typeof window==='undefined'?globalThis:window,function(root){
  'use strict';
  const KEY='protrader.oracle.learning.v1';
  const INTRADAY=['4h','1h','15m','5m'];
  const STEPS=['Setup','Reasoning','Plan'];
  const METHODS={'continuation':'Trend continuation','breakout':'Breakout','range-reversal':'Range reversal','other':'Another method / uncertain'};
  const HIGHER={'1m':'15m','5m':'1h','15m':'1h','1h':'4h','4h':'1d'};
  const clone=v=>JSON.parse(JSON.stringify(v));
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const number=v=>v===''||v===null||v===undefined?null:Number.isFinite(Number(v))?Number(v):null;
  const id=()=>typeof root.crypto?.randomUUID==='function'?root.crypto.randomUUID():`oracle-${Date.now()}-${Math.random().toString(36).slice(2,9)}`;
  const when=v=>{if(!v)return'Unknown time';const d=new Date(typeof v==='number'?v*1000:v);return Number.isNaN(d.valueOf())?'Unknown time':d.toLocaleString(undefined,{dateStyle:'medium',timeStyle:'short'});};
  const fmt=v=>typeof v==='number'&&Number.isFinite(v)?v.toLocaleString(undefined,{maximumFractionDigits:5}):'Unknown';
  const blankState=()=>({version:1,draft:null,savedDrafts:[],records:[],savedAnalyses:[],reviewTrash:null,tradeNotes:[],selectedAnalysisId:null,selectedId:null,screen:'draft',updatedAt:null});
  function makeHypothesis(context){
    const account=context.account||{};
    return {version:1,id:id(),symbol:context.symbol,label:context.label||context.symbol,timeframe:HIGHER[context.timeframe]?context.timeframe:'15m',method:'continuation',action:'wait',observation:'',reasoning:'',thesisLevel:null,entryCondition:'conditional',targetBasis:'visible-structure',invalidation:{condition:'close-below',price:null,reason:''},plan:{entry:null,stop:null,target:null,quantity:null,cost:null,openRisk:number(account.openRisk),realizedLoss:number(account.realizedLoss),perIdeaLimit:number(account.perIdeaLimit),combinedLimit:number(account.combinedLimit),dailyLossLimit:number(account.dailyLossLimit)},wait:{condition:'',price:null,reason:''}};
  }
  const object=value=>!!value&&typeof value==='object'&&!Array.isArray(value);
  const sameJSON=(a,b)=>{
    const ordered=value=>Array.isArray(value)?value.map(ordered):object(value)?Object.fromEntries(Object.keys(value).sort().map(key=>[key,ordered(value[key])])):value;
    return JSON.stringify(ordered(a))===JSON.stringify(ordered(b));
  };
  function hypothesisShape(h){
    return object(h)&&h.version===1&&['id','symbol','label','timeframe','method','action','observation','reasoning','entryCondition','targetBasis'].every(k=>typeof h[k]==='string')&&!!h.id&&!!h.symbol&&
      object(h.invalidation)&&typeof h.invalidation.condition==='string'&&typeof h.invalidation.reason==='string'&&object(h.plan)&&object(h.wait)&&typeof h.wait.condition==='string'&&typeof h.wait.reason==='string';
  }
  function snapshotShape(s){
    return object(s)&&typeof s.id==='string'&&typeof s.symbol==='string'&&Number.isFinite(s.asOf)&&object(s.series)&&Object.values(s.series).every(row=>object(row)&&typeof row.status==='string'&&Array.isArray(row.candles)&&row.candles.every(object));
  }
  function reviewShape(v){return object(v)&&typeof v.assessment==='string'&&['constraints','concerns','unknowns','facts','whatChanges','limitations'].every(k=>Array.isArray(v[k])&&v[k].every(f=>typeof f==='string'||object(f)));}
  function viewShape(v){
    return object(v)&&hypothesisShape(v.hypothesis)&&snapshotShape(v.snapshot)&&reviewShape(v.review)&&v.snapshot.symbol===v.hypothesis.symbol&&(!v.review.snapshotId||v.review.snapshotId===v.snapshot.id)&&(!v.review.hypothesisId||v.review.hypothesisId===v.hypothesis.id)&&
      (!v.comparison||object(v.comparison)&&['factsAgreed','interpretationsDiffer','missing','notes'].every(k=>Array.isArray(v.comparison[k])&&v.comparison[k].every(f=>typeof f==='string'||object(f))));
  }
  function reflectionShape(r){return (!r.decision||object(r.decision)&&typeof r.decision.action==='string'&&typeof r.decision.reason==='string')&&(!r.decisionDraft||object(r.decisionDraft)&&typeof r.decisionDraft.action==='string'&&typeof r.decisionDraft.reason==='string');}
  function recordShape(r){return viewShape(r)&&typeof r.id==='string'&&reflectionShape(r)&&Array.isArray(r.reassessments)&&r.reassessments.every(v=>viewShape(v)&&sameJSON(v.hypothesis,r.hypothesis)&&Array.isArray(v.changes)&&reflectionShape(v));}
  function draftShape(d){
    return object(d)&&hypothesisShape(d.hypothesis)&&object(d.context)&&d.context.symbol===d.hypothesis.symbol&&Number.isInteger(d.step)&&d.step>=0&&d.step<=2&&
      (!d.context.supportedTimeframes||Array.isArray(d.context.supportedTimeframes))&&
      (d.snapshot==null?d.step===0:snapshotShape(d.snapshot)&&d.snapshot.symbol===d.hypothesis.symbol)&&
      ['parentId','originReviewId'].every(k=>d[k]==null||typeof d[k]==='string')&&(!d.originAnalysis||object(d.originAnalysis));
  }
  function analysisShape(a){return object(a)&&typeof a.id==='string'&&!!a.id&&snapshotShape(a.snapshot)&&object(a.analysis)&&Array.isArray(a.questions);}
  function trashShape(t){return object(t)&&typeof t.removedAt==='string'&&Number.isFinite(new Date(t.removedAt).valueOf())&&Array.isArray(t.items)&&t.items.length>0&&t.items.every(item=>object(item)&&Number.isInteger(item.index)&&item.index>=0&&analysisShape(item.review))&&new Set(t.items.map(item=>item.review.id)).size===t.items.length;}
  function readState(storage){
    try{
      if(!storage||typeof storage.getItem!=='function')throw Error('Browser storage unavailable');const raw=storage.getItem(KEY);if(!raw)return{state:blankState(),warning:''};
      const parsed=JSON.parse(raw);
      if(!object(parsed)||parsed.version!==1||!Array.isArray(parsed.records)||!parsed.records.every(recordShape))throw Error('Invalid learning record');
      const state=blankState();state.records=parsed.records;if(parsed.savedAnalyses!==undefined){if(!Array.isArray(parsed.savedAnalyses)||!parsed.savedAnalyses.every(a=>object(a)&&typeof a.id==='string'&&snapshotShape(a.snapshot)&&object(a.analysis)&&Array.isArray(a.questions)))throw Error('Invalid saved market analysis');state.savedAnalyses=parsed.savedAnalyses.map(a=>({...a,marketReview:marketReviewFor(a.marketReview,a.snapshot)}));}state.selectedId=typeof parsed.selectedId==='string'?parsed.selectedId:null;state.updatedAt=parsed.updatedAt||null;
      if(parsed.draft!=null){if(!draftShape(parsed.draft))throw Error('Invalid hypothesis draft');state.draft=parsed.draft;}
      if(parsed.savedDrafts!==undefined){if(!Array.isArray(parsed.savedDrafts)||!parsed.savedDrafts.every(draftShape))throw Error('Invalid retained hypothesis draft');state.savedDrafts=parsed.savedDrafts;}
      const draftIds=[state.draft,...state.savedDrafts].filter(Boolean).map(d=>d.hypothesis.id);if(new Set(draftIds).size!==draftIds.length)throw Error('Duplicate hypothesis draft');
      if(parsed.tradeNotes!==undefined){if(!Array.isArray(parsed.tradeNotes)||!parsed.tradeNotes.every(n=>object(n)&&typeof n.key==='string'&&typeof n.text==='string'&&typeof n.draftText==='string'))throw Error('Invalid trade notes');state.tradeNotes=parsed.tradeNotes;}
      state.screen=!state.draft&&state.selectedId&&state.records.some(r=>r.id===state.selectedId)?'review':'draft';
      let trashWarning='';
      if(parsed.reviewTrash!=null){
        if(trashShape(parsed.reviewTrash))state.reviewTrash={removedAt:parsed.reviewTrash.removedAt,items:parsed.reviewTrash.items.map(item=>({index:item.index,review:{...item.review,marketReview:marketReviewFor(item.review.marketReview,item.review.snapshot)}}))};
        else trashWarning='The last removal could not be restored. Your saved reviews, trades, plans and reflections are still available.';
      }
      return{state,warning:trashWarning,readable:true};
    }catch(_){return{state:blankState(),warning:'Saved Journal learning records could not be read. Existing storage is untouched. This session can continue; export a copy before closing.'};}
  }
  function writeState(targetStorage,state){try{if(!targetStorage)throw Error('No storage');const raw=JSON.stringify(state);targetStorage.setItem(KEY,raw);if(targetStorage===storage)storageBaseline=raw;return'';}catch(_){return'Your browser could not save this learning record. Keep this tab open and export a copy before closing; reload may lose these changes.';}}
  function exportRecord(state){return{version:1,title:'Journal · Evidence, plan & reflection',exportedAt:new Date().toISOString(),persistence:persistenceLabel(),reviewMethod:'Paper-plan checks use transparent rules, not an AI assessment. Saved marketReview fields contain separately requested agent interpretations; neither is a validated probability.',records:clone(state.records),savedAnalyses:clone(state.savedAnalyses||[]),reviewTrash:state.reviewTrash?clone(state.reviewTrash):null,draft:state.draft?clone(state.draft):null,savedDrafts:clone(state.savedDrafts||[]),tradeNotes:clone(state.tradeNotes||[])};}
  function mtfFields(value){
    const prose=v=>typeof v==='string'&&v.trim().length>=4&&v.length<=700;
    const keys=['governing','setupCondition','setupInvalidation','contextInvalidation'];
    if(!value||value.profile!=='intraday-v1'||!['aligned','compatible-pullback','conflicting','mixed','undetermined','incomplete'].includes(value.relationship)||!keys.every(k=>prose(value[k]))||!Array.isArray(value.frames)||value.frames.length!==4)return null;
    if(!INTRADAY.every(tf=>value.frames.filter(f=>f?.timeframe===tf&&prose(f.reading)&&prose(f.evidence)).length===1))return null;
    return {profile:'intraday-v1',relationship:value.relationship,...Object.fromEntries(keys.map(k=>[k,value[k].trim()])),frames:INTRADAY.map(tf=>{const f=value.frames.find(f=>f.timeframe===tf);return{timeframe:tf,reading:f.reading.trim(),evidence:f.evidence.trim()};})};
  }
  function marketReviewFor(value,snapshot){
    const fields=['reading','support','concern','whatChanges','limits'];
    if(!object(value)||typeof value.reviewId!=='string'||!value.reviewId||value.reviewId.length>160||!Number.isFinite(value.at)||!Number.isFinite(new Date(value.at).valueOf())||value.at<=0||value.snapshotId!==snapshot.id||value.dataReference!==snapshot.dataReference||!fields.every(k=>typeof value[k]==='string'&&value[k].trim().length>=8&&value[k].length<=1800))return null;
    const mtf=snapshot.profile==='intraday-v1'?mtfFields(value.mtf):null;if(snapshot.profile==='intraday-v1'&&!mtf)return null;
    return {...Object.fromEntries(fields.map(k=>[k,value[k]])),...(mtf?{mtf}:{}),reviewId:value.reviewId,at:value.at,snapshotId:value.snapshotId,dataReference:value.dataReference};
  }
  function marketReviewHTML(saved){const r=marketReviewFor(saved.marketReview,saved.snapshot);if(!r)return'';return `<section class="ow-note"><h3>Oracle’s market review</h3><p>${esc(r.reading)}</p>${r.mtf?`<details><summary>Saved four-timeframe hierarchy · ${esc(r.mtf.relationship.replaceAll('-',' '))}</summary><p>${esc(r.mtf.governing)}</p>${r.mtf.frames.map(f=>`<h4>${esc(f.timeframe.toUpperCase())}</h4><p>${esc(f.reading)}</p><p>${esc(f.evidence)}</p>`).join('')}<h4>Setup condition</h4><p>${esc(r.mtf.setupCondition)}</p><h4>Setup invalidated if</h4><p>${esc(r.mtf.setupInvalidation)}</p><h4>Higher context changes if</h4><p>${esc(r.mtf.contextInvalidation)}</p></details>`:''}${[['What supports this','support'],['Main concern','concern'],['What would change this view?','whatChanges'],['Review limits','limits']].map(([label,key])=>`<h4>${label}</h4><p>${esc(r[key])}</p>`).join('')}<p class="ow-hint">Agent interpretation of the saved evidence · generated ${esc(new Date(r.at).toLocaleString())}. This is not a verified prediction.</p></section>`;}
  function importAnalysis(packet){
    if(!object(packet)||!snapshotShape(packet.snapshot)||!object(packet.analysis))throw Error('A saved analysis needs its frozen market snapshot and analysis.');
    return clone({version:1,id:typeof packet.id==='string'&&packet.id?packet.id:id(),savedAt:new Date().toISOString(),snapshot:packet.snapshot,analysis:packet.analysis,marketReview:marketReviewFor(packet.marketReview,packet.snapshot),questions:Array.isArray(packet.questions)?packet.questions:[],lessonRef:packet.lessonRef||null});
  }
  function saveAnalysis(packet){
    if(accountChanging)throw Error('Wait for your account to finish changing before saving a review.');
    if(!state)throw Error('Open the Journal workspace before saving an analysis.');
    const imported=importAnalysis(packet),existing=(state.savedAnalyses||[]).find(a=>a.id===imported.id);
    if(existing)return clone(existing);
    state.savedAnalyses=state.savedAnalyses||[];state.savedAnalyses.push(imported);save();if(dialog?.open)render();return clone(imported);
  }
  function createRecord(data,recordId=id()){
    const h=data.hypothesis,s=data.snapshot,v=data.review;
    if(!h||!s||!v||s.symbol!==h.symbol||v.snapshotId&&v.snapshotId!==s.id||v.hypothesisId&&v.hypothesisId!==h.id)throw Error('Review evidence does not match the hypothesis.');
    return clone({version:1,id:recordId,parentId:data.parentId||null,originReviewId:data.originReviewId||null,originAnalysis:data.originAnalysis||null,lessonRef:data.lessonRef||null,hypothesis:h,snapshot:s,review:v,aria:data.aria??null,comparison:data.comparison??null,decision:null,reflection:null,decisionDraft:{action:'retain',reason:''},reassessments:[]});
  }
  function appendReassessment(record,item){
    if(!sameJSON(item.hypothesis,record.hypothesis))throw Error('A reassessment must preserve the same declared hypothesis. Save a linked revision for changed reasoning or plans.');
    if(item.snapshot?.symbol!==record.hypothesis.symbol||!item.review||item.review.snapshotId&&item.review.snapshotId!==item.snapshot.id||item.review.hypothesisId&&item.review.hypothesisId!==record.hypothesis.id)throw Error('New evidence does not match this hypothesis and market record.');
    const updated=clone(record);updated.reassessments.push({...clone(item),decision:null,reflection:null,decisionDraft:{action:'retain',reason:''}});return updated;
  }
  function decideRecord(record,decision){
    if(record.decision)throw Error('A saved reflection is retained. Revise the hypothesis in a new record.');
    if(!['retain','revise','withdraw'].includes(decision.action)||typeof decision.reason!=='string'||decision.reason.trim().length<15)throw Error('Explain the decision using at least 15 characters.');
    const updated=clone(record);updated.decision={action:decision.action,reason:decision.reason.trim(),at:decision.at||new Date().toISOString(),reviewSnapshotId:decision.reviewSnapshotId||record.snapshot.id};updated.reflection=updated.decision.reason;delete updated.decisionDraft;return updated;
  }
  function decideReassessment(record,index,decision){
    if(!Number.isInteger(index)||index<0||index>=record.reassessments.length)throw Error('Choose an existing reassessment before recording its decision.');
    const updated=clone(record);updated.reassessments[index]=decideRecord(updated.reassessments[index],decision);return updated;
  }
  function validateHypothesis(h,step){
    if(step===0){if(!h.symbol||!HIGHER[h.timeframe]||!METHODS[h.method]||!['long','short','wait'].includes(h.action))return'Choose a supported horizon, method and a direction or deliberate wait.';return'';}
    if(step===1){if(String(h.observation||'').trim().length<15||String(h.reasoning||'').trim().length<15||String(h.invalidation.reason||'').trim().length<15||!(number(h.invalidation.price)>0)||!(number(h.thesisLevel)>0))return'Write a chart observation, your interpretation and an invalidation explanation (at least 15 characters each). Add a positive thesis reference and invalidation price.';return'';}
    if(h.action==='wait'&&(String(h.wait.reason||'').trim().length<15||String(h.wait.condition||'').trim().length<15||!(number(h.wait.price)>0)))return'For a deliberate wait, record why, an observable condition to revisit (at least 15 characters each), and a positive reference price.';
    if(h.action!=='wait'&&['entry','stop','target','quantity'].some(k=>!(number(h.plan[k])>0)))return'Add a positive entry, stop, target and quantity for your written paper plan. Unknown costs or risk inputs may stay blank; The structured review will withhold a conclusion where they are essential.';
    return'';
  }
  function snapshotChanges(before,after){
    const changes=[],different=(a,b)=>JSON.stringify(a)!==JSON.stringify(b);
    for(const tf of new Set([...Object.keys(before.series||{}),...Object.keys(after.series||{})])){
      const a=before.series?.[tf],b=after.series?.[tf],last=x=>x?.candles?.[x.candles.length-1];
      if(a?.status!==b?.status)changes.push(`${tf}: data state ${a?.status||'missing'} → ${b?.status||'missing'}.`);
      if(a?.source!==b?.source)changes.push(`${tf}: source ${a?.source||'unknown'} → ${b?.source||'unknown'}.`);
      if(a?.error!==b?.error)changes.push(`${tf}: provider error ${a?.error||'none'} → ${b?.error||'none'}.`);
      const oldBars=a?.candles||[],newBars=b?.candles||[],oldByTime=new Map(oldBars.map(c=>[c.time,c])),newByTime=new Map(newBars.map(c=>[c.time,c]));
      const added=newBars.filter(c=>!oldByTime.has(c.time)).length,removed=oldBars.filter(c=>!newByTime.has(c.time)).length;
      if(added||removed)changes.push(`${tf}: ${added} supplied bars added and ${removed} removed (${oldBars.length} → ${newBars.length} bars).`);
      if(last(a)?.time!==last(b)?.time)changes.push(`${tf}: last supplied bar opened at ${when(last(a)?.time)} → ${when(last(b)?.time)}.`);
      const revised={open:0,high:0,low:0,close:0};
      for(const bar of newBars){const old=oldByTime.get(bar.time);if(old)for(const key of Object.keys(revised))if(old[key]!==bar[key])revised[key]++;}
      const revisions=Object.entries(revised).filter(([,n])=>n).map(([key,n])=>`${n} ${key} ${n===1?'value':'values'}`);
      if(revisions.length)changes.push(`${tf}: provider OHLC revisions in overlapping history: ${revisions.join(', ')}. Earlier structure and review inputs may therefore differ.`);
      if(last(a)?.close!==last(b)?.close)changes.push(`${tf}: last supplied close ${fmt(last(a)?.close)} → ${fmt(last(b)?.close)}.`);
    }
    for(const group of ['quote','spec','account','settings']){
      const a=before[group]||{},b=after[group]||{};
      for(const key of new Set([...Object.keys(a),...Object.keys(b)]))if(different(a[key],b[key])){
        const display=v=>v===undefined||v===null?'unknown':typeof v==='number'?fmt(v):typeof v==='object'?JSON.stringify(v):String(v);
        changes.push(`${{quote:'Quote',spec:'Paper instrument specification',account:'Paper exposure / limit',settings:'Recorded workspace setting'}[group]} · ${key}: ${display(a[key])} → ${display(b[key])}.`);
      }
    }
    if(!changes.length)changes.push('No supplied OHLC, source, data-state, quote, specification, exposure or risk-limit change was found. A later capture time alone is not new confirmation.');
    if(before.asOf!==after.asOf)changes.push(`Evidence cutoff: ${when(before.asOf)} → ${when(after.asOf)}. A bar is assessed only when completed by its own cutoff.`);
    if(before.dataReference!==after.dataReference)changes.push(`Retained evidence reference: ${before.dataReference||before.id} → ${after.dataReference||after.id}. Both versions remain available in the export.`);
    return changes;
  }

  let doc,adapter,state,dialog,storage,storageReadable=true,warning='',busy=false,request=0,controller=null,error='',selectedReview=-1,comparisonVisible=false,changeVisible=false,returnFocus=null,pendingDraft=null,homeTab='trades',selectedTradeKey=null,noteStatus='',reviewNotice='',reviewNoticeError=false,storageBaseline=null;
  const draft=()=>state.draft;
  const hypothesis=()=>draft()?.hypothesis;
  const current=()=>state.records.find(r=>r.id===state.selectedId);
  const activeReview=()=>selectedReview>=0?current()?.reassessments[selectedReview]:current();
  function safeContext(){try{return adapter.getContext()||{};}catch(_){return{};}}
  let accountChanging=false;
  function persistenceLabel(){try{return root.ProTraderStorageStatus?.()||'Saved on this browser only. Export a backup before clearing site data.';}catch(_){return'Saved on this browser only. Export a backup before clearing site data.';}}
  function save(){if(accountChanging)return;state.updatedAt=new Date().toISOString();if(storageReadable)warning=writeState(storage,state);const node=doc?.getElementById('owSave');if(node){node.textContent=warning||persistenceLabel();node.classList.toggle('ow-warning',!!warning);}renderPanel();}
  function setPath(object,path,value){const parts=path.split('.');let target=object;for(let i=0;i<parts.length-1;i++)target=target[parts[i]];target[parts[parts.length-1]]=value;}
  function getPath(object,path){return path.split('.').reduce((v,k)=>v?.[k],object);}
  function field(path,label,hint='',type='textarea'){
    const val=getPath(hypothesis(),path),fieldId='ow-'+path.replace(/\./g,'-');
    const input=type==='textarea'?`<textarea id="${fieldId}" data-field="${path}" maxlength="3000" rows="3">${esc(val)}</textarea>`:`<input id="${fieldId}" data-field="${path}" type="number" inputmode="decimal" step="any" min="0" value="${esc(val)}"/>`;
    return`<label class="ow-field" for="${fieldId}">${label}${input}${hint?`<span class="ow-hint">${hint}</span>`:''}</label>`;
  }
  function select(path,label,options,hint=''){
    const fieldId='ow-'+path.replace(/\./g,'-');return`<label class="ow-field" for="${fieldId}">${label}<select id="${fieldId}" data-field="${path}">${Object.entries(options).map(([v,t])=>`<option value="${esc(v)}" ${getPath(hypothesis(),path)===v?'selected':''}>${esc(t)}</option>`).join('')}</select>${hint?`<span class="ow-hint">${hint}</span>`:''}</label>`;
  }
  function refsHTML(refs){if(!Array.isArray(refs)||!refs.length)return'';refs=refs.filter(v=>typeof v==='string'||object(v));return`<p class="ow-hint">${refs.map(r=>typeof r==='string'?esc(r):esc([r.timeframe||r.tf,r.source,r.barTime?when(r.barTime):''].filter(Boolean).join(' · '))).join(' · ')}</p>`;}
  function findingHTML(f){
    if(typeof f==='string')return`<li class="ow-item">${esc(f)}</li>`;
    return`<li class="ow-item"><h4>${esc(f.title||f.area||f.id||'Evidence')}</h4><dl><dt>Observed fact</dt><dd>${esc(f.fact||'Not supplied')}</dd><dt>Why it matters to this idea</dt><dd>${esc(f.relevance||'No relevance supplied')}</dd><dt>What could resolve it</dt><dd>${esc(f.resolution||'No resolution supplied')}</dd></dl>${refsHTML(f.refs)}</li>`;
  }
  function findings(title,list,empty){return`<section class="ow-section"><h3>${title}</h3>${list?.length?`<ul class="ow-fact-list">${list.map(findingHTML).join('')}</ul>`:`<p class="ow-muted">${empty}</p>`}</section>`;}
  function snapshotSummary(s){return`<div class="ow-context"><span class="ow-badge">${esc(s.label||s.symbol)}</span><span class="ow-badge">${esc(s.provider||'Source unknown')}</span><span class="ow-badge">Evidence cutoff ${esc(when(s.asOf))}</span></div><p class="ow-hint"><strong>Frozen historical evidence, not a live assessment.</strong> Only candles completed by the cutoff may be assessed. Data requests completed ${esc(when(s.capturedAt))}. Times use your browser’s local timezone.</p><p class="ow-hint">Snapshot ${esc(s.id)}${s.dataReference?' · '+esc(s.dataReference):''}. New prices cannot rewrite this snapshot or its original review.</p>`;}
  function seriesSummary(s){return`<div class="ow-table-wrap"><table class="ow-table"><thead><tr><th scope="col">Interval</th><th scope="col">Data state</th><th scope="col">Supplied bars</th><th scope="col">Source</th></tr></thead><tbody>${Object.entries(s.series||{}).map(([tf,row])=>`<tr><th scope="row">${esc(tf)}</th><td>${esc(row.status||'Unknown')}${row.error?`<br/>${esc(row.error)}`:''}</td><td>${Array.isArray(row.candles)?row.candles.length:0}</td><td>${esc(row.source||'Unknown')}</td></tr>`).join('')}</tbody></table></div>`;}
  function chart(s,tf){
    if(s.series?.[tf]?.status!=='ready')return`<div class="ow-empty">${esc(tf)} chart unavailable: ${esc(s.series?.[tf]?.error||s.series?.[tf]?.status||'No supplied data')}. No price series is drawn from an invalid or unavailable interval.</div>`;
    const seconds={'1m':60,'5m':300,'15m':900,'1h':3600,'4h':14400,'1d':86400}[tf];
    const bars=(s.series?.[tf]?.candles||[]).filter(c=>['time','open','high','low','close'].every(k=>Number.isFinite(c[k]))&&c.time+seconds<=s.asOf).slice(-36);
    if(!bars.length)return`<div class="ow-empty">No completed ${esc(tf)} candles available in this snapshot. The structured review will show the missing evidence; a chart cannot be fabricated.</div>`;
    const low=Math.min(...bars.map(c=>c.low)),high=Math.max(...bars.map(c=>c.high)),range=high-low||1,y=p=>198-(p-low)/range*154,step=540/bars.length;
    return`<svg class="ow-chart" viewBox="0 0 620 245" role="img" aria-label="${esc(s.label||s.symbol)}, last ${bars.length} completed ${esc(tf)} candles from the frozen ${esc(s.provider)} snapshot. Use the price table for exact values."><text x="20" y="22">${esc(tf)} · completed bars only · ${esc(s.provider)}</text>${bars.map((b,i)=>{const x=20+step*(i+.5),top=Math.min(y(b.open),y(b.close)),height=Math.max(1,Math.abs(y(b.open)-y(b.close)));return`<g class="${b.close>=b.open?'ow-up':'ow-down'}"><line x1="${x}" x2="${x}" y1="${y(b.high)}" y2="${y(b.low)}"/><rect x="${x-step*.28}" y="${top}" width="${step*.56}" height="${height}"/></g>`;}).join('')}<text x="565" y="48">${esc(fmt(high))}</text><text x="565" y="202">${esc(fmt(low))}</text><text x="20" y="228">${esc(when(bars[0].time))}</text><text x="350" y="228">${esc(when(bars[bars.length-1].time+seconds))}</text></svg><p class="ow-hint">The latest completed ${esc(tf)} close shown is ${esc(fmt(bars[bars.length-1].close))}. Forming bars are excluded. Session gaps may be present; no future bars are shown.</p><details><summary>Exact prices for the last 12 completed bars</summary><div class="ow-table-wrap"><table class="ow-table"><thead><tr><th>Bar opened</th><th>Open</th><th>High</th><th>Low</th><th>Close</th></tr></thead><tbody>${bars.slice(-12).map(b=>`<tr><th scope="row">${esc(when(b.time))}</th>${['open','high','low','close'].map(k=>`<td>${esc(fmt(b[k]))}</td>`).join('')}</tr>`).join('')}</tbody></table></div></details>`;
  }
  function rulesDisclosure(){
    return `<details class="ow-rules"><summary>How these review rules work</summary><p>These are bounded teaching conventions for a structured review, not universal trading rules or a validated edge. Changing the declared method can change which context matters.</p><ul><li><strong>Trend continuation:</strong> the displacement from the first to last close in the latest 20 completed bars must point in the proposed direction on both the selected interval and its declared higher interval.</li><li><strong>Breakout:</strong> the latest completed close is compared with the high/low boundary of the preceding 20 bars, excluding that latest bar. A pending breakout stays conditional until the relevant boundary close is observed.</li><li><strong>Range reversal:</strong> the latest completed candle must touch the preceding 20-bar low for a long idea or high for a short idea, close back inside that boundary, and close in the proposed direction. Opposing higher-interval displacement is context to explain, not an automatic reversal veto.</li><li><strong>Claimed closed-confirmation entry:</strong> entry must be within one mean candle range of the latest completed close. Mean range is the average high minus low of the latest 20 completed candles. A farther pending price should be labelled conditional.</li><li><strong>Target:</strong> a visible-structure target is compared with the relevant preceding 20-bar boundary, using the smaller of one mean candle range or 10% of the visible high-low span as tolerance. A fixed-multiple target is an arithmetic assumption, not evidence that price will reach it.</li><li><strong>Thesis reference:</strong> the reference must sit within the preceding 20-bar low/high window expanded by one mean candle range on either side. A level beyond this bounded window is a material concern, including a breakout close used as the thesis reference.</li><li><strong>Invalidation and risk:</strong> the supported directional methods require an adverse-side close condition, invalidation at or beyond the adverse side of the thesis reference, a stop covering that invalidation, consistent price geometry and cost-inclusive paper arithmetic within available budgets. Missing essential inputs remain unknown.</li><li><strong>Written reasoning:</strong> the form checks completeness; it cannot semantically assess your explanation or determine whether your prose is sound. You must check the connection between the observation, thesis and invalidation yourself. Another method remains unassessed.</li></ul><p class="ow-hint">Only completed, sufficiently recent candles with valid intervals are assessed at the frozen cutoff. Price candles do not supply news, macro-event, order-flow, hidden-order or institutional-intent evidence.</p></details>`;
  }

  function contextForm(){
    const h=hypothesis(),ctx=draft().context;
    return`<h2 id="owTitle">Start a plan</h2><p class="ow-muted">Choose your setup. Your draft saves as you go.</p>${!HIGHER[ctx.timeframe]?`<p class="ow-note">${esc(ctx.timeframe)} is not supported by the plan checks. Choose an interval below.</p>`:''}<div class="ow-context"><strong>${esc(ctx.label||ctx.symbol||'No market selected')}</strong><span class="ow-badge">Paper plan</span></div><p class="ow-hint">To plan another market, select it on the chart first.</p><div class="ow-grid">${select('timeframe','Timeframe',Object.fromEntries((ctx.supportedTimeframes||Object.keys(HIGHER)).map(tf=>[tf,tf+' candles'])), 'Also checks '+(HIGHER[h.timeframe]||'higher')+' context.')}${select('method','Approach',METHODS)}</div><fieldset class="ow-direction"><legend>What are you considering?</legend>${[['wait','Wait'],['long','Long'],['short','Short']].map(([v,l])=>`<label class="ow-choice"><input type="radio" name="ow-action" data-field="action" value="${v}" ${h.action===v?'checked':''}/><span>${l}</span></label>`).join('')}</fieldset><p class="ow-hint">Next, capture the chart evidence for your reasoning. A plan does not place a trade.</p><details><summary>About the plan checks</summary><p>These rule-based checks assess the written plan, not your chance of profit. Another method stays unassessed.</p>${rulesDisclosure()}</details>${draft().parentId?'<p class="ow-note">Linked revision · your earlier plan stays unchanged.</p>':''}`;
  }

  function evidenceForm(){
    const h=hypothesis(),s=draft().snapshot;
    return`<h2 id="owTitle">Explain your idea</h2><p class="ow-muted">What you see, what it means, and what would prove it wrong.</p><div class="ow-context"><strong>${esc(h.label)}</strong><span class="ow-badge">${esc(h.timeframe)} · ${esc(h.action)}</span></div>${draft().originReviewId?`<details><summary>Saved Oracle reading</summary><p>${esc(draft().originAnalysis?.marketReview?.reading||analysisSummary(draft().originAnalysis||{}))}</p><p class="ow-hint">${s.profile==='intraday-v1'?'This intraday review uses a 15m plan with 1h context. All four captured histories remain with the saved review. ':''}Your reasoning below stays separate from Oracle’s view.</p></details><div class="ow-grid">${select('method','Approach',METHODS)}${select('action','My idea',{'wait':'Wait','long':'Long','short':'Short'})}</div>`:''}<details><summary>View captured chart &amp; prices</summary>${snapshotSummary(s)}${chart(s,h.timeframe)}<details><summary>Higher timeframe · ${esc(HIGHER[h.timeframe])}</summary>${chart(s,HIGHER[h.timeframe])}</details>${seriesSummary(s)}</details>${field('observation','What do you see?','Describe one completed candle, price level or visible pattern.')}${field('reasoning','What do you expect, and why?','Link the evidence to your idea. Include a concern or uncertainty.')}<div class="ow-grid">${field('thesisLevel','Key price level','The visible level your idea depends on.','number')}${field('invalidation.price','Invalidation price','The price that would challenge your idea.','number')}</div>${select('invalidation.condition','My idea is challenged when',{'close-below':'A completed candle closes below invalidation','close-above':'A completed candle closes above invalidation'})}${field('invalidation.reason','Why would that change your view?','Explain how this breaks your reasoning.')}<p class="ow-hint">Each explanation needs at least 15 characters. These checks measure completeness, not the quality of your writing.</p>${rulesDisclosure()}`;
  }
  function planForm(){
    const h=hypothesis(),s=draft().snapshot,spec=s.spec||{};
    return`<h2 id="owTitle">${h.action==='wait'?'When will you look again?':'Set your paper plan'}</h2><div class="ow-context"><span class="ow-badge">${esc(h.label)}</span><span class="ow-badge">${esc(h.timeframe)} · ${esc(METHODS[h.method])}</span><span class="ow-badge">${esc(h.action==='wait'?'Wait':h.action==='long'?'Long paper idea':'Short paper idea')}</span></div><p>Record your decision; no trade is placed.</p>${h.action==='wait'?`${field('wait.reason','Why wait?','Tie your reason to the evidence or an essential unknown.')}${field('wait.condition','What needs to happen next?','Be concrete. Rechecking a condition is not an instruction to enter.')}${field('wait.price','Revisit reference price','','number')}`:`${select('entryCondition','Entry assumption',{'conditional':'Conditional — entry has not been confirmed','closed-confirmation':'I believe the completed candles confirm the entry'})}<div class="ow-grid">${field('plan.entry','Entry price','','number')}${field('plan.stop','Stop price','Long: at or below invalidation. Short: at or above invalidation. Moving it to fit a budget can change the thesis.','number')}${field('plan.target','Target price','','number')}${field('plan.quantity','Quantity in paper lots',spec.quantityStep?`Paper quantity step: ${fmt(spec.quantityStep)}. This form does not alter a position.`:'Instrument specification is unavailable; exposure cannot be assumed.','number')}</div>${select('targetBasis','How did I choose the target?',{'visible-structure':'Visible structure in the captured chart','fixed-multiple':'A predeclared reward/risk multiple','other':'Another basis / not yet assessed'})}${field('plan.cost',`Estimated total round-trip costs (${esc(spec.currency||'account currency')})`,'Enter a sourced or deliberate paper estimate, including relevant spread/fees/slippage. Blank means unknown; it is never treated as zero.','number')}<details><summary>Paper risk context and assumptions</summary><p class="ow-hint">These are local paper-review inputs, not broker settings or execution locks. Prefilled exposure and limits are a snapshot of the paper workspace. If unknown, leave blank. A limit breach is a constraint within this written plan; it cannot block or authorize an order.</p><div class="ow-grid">${field('plan.openRisk','Existing open paper risk','','number')}${field('plan.realizedLoss','Realized paper loss today','','number')}${field('plan.perIdeaLimit','Per-idea loss limit','','number')}${field('plan.combinedLimit','Combined open-risk limit','','number')}${field('plan.dailyLossLimit','Daily loss limit','','number')}</div><p class="ow-hint">${spec.source?`Specification source: ${esc(spec.source)}. Value per price unit per paper lot: ${esc(fmt(spec.valuePerPriceUnit))} ${esc(spec.currency||'')}.`:'No instrument specification supplied. Risk arithmetic will remain unknown.'}</p></details>`}<p class="ow-hint">Save to check this plan against its captured evidence. ARIA comparison is available afterwards.</p><details><summary>Re-read my hypothesis</summary><p><strong>Observation:</strong> ${esc(h.observation)}</p><p><strong>Interpretation:</strong> ${esc(h.reasoning)}</p><p><strong>Invalidation:</strong> ${esc(h.invalidation.condition)} ${esc(fmt(h.invalidation.price))}. ${esc(h.invalidation.reason)}</p></details>`;
  }
  function renderDraft(){
    if(!draft())return`<h2 id="owTitle">Start from your own market reading</h2><p>Choose an instrument in the workspace, then record a hypothesis before the structured review checks it.</p><div class="ow-empty">No active hypothesis yet.</div><div class="ow-actions"><button class="ow-primary" data-action="new">Start an idea on the current market</button>${state.records.length?'<button data-action="history">View learning records</button>':''}</div>`;
    return`<ol class="ow-progress" aria-label="Hypothesis progress">${STEPS.map((s,i)=>`<li ${draft().step===i?'aria-current="step"':''}>${i+1}. ${s}</li>`).join('')}</ol>${draft().step===0?contextForm():draft().step===1?evidenceForm():planForm()}${error?`<p class="ow-error" role="alert">${esc(error)}</p>`:''}${busy?'<div class="ow-pending" role="status"><span class="ow-spinner"></span><span>Capturing chart evidence…</span></div>':''}<div class="ow-actions">${draft().step>0?'<button data-action="back" '+(busy?'disabled':'')+'>Back</button>':''}<button class="ow-primary" data-action="next" ${busy?'disabled':''}>${draft().step===0?'Capture chart & continue':draft().step===1?'Continue to plan':'Save & check plan'}</button><button class="ow-subtle" data-action="history" data-section="plans">Back to plans</button></div>`;
  }
  function metricHTML(metrics){
    if(!metrics||!Object.prototype.hasOwnProperty.call(metrics,'risk'))return'';
    if(!metrics.risk)return'<details><summary>Deterministic paper arithmetic</summary><p>No complete, compatible directional paper-risk calculation is available in this review. Check the unknowns and constraints above. A deliberate wait needs no position-size calculation.</p></details>';
    const labels={distance:'Entry-to-stop distance',rewardDistance:'Entry-to-target distance',quantity:'Paper lots',valuePerPriceUnit:'USD per price unit per paper lot',cost:'Declared total round-trip costs',grossLoss:'Planned stop loss before costs',grossReward:'Gross planned target reward',plannedLoss:'Planned stop loss including costs',netReward:'Planned target reward after costs',grossRewardRisk:'Gross reward/risk',netRewardRisk:'Net reward/risk',combinedRisk:'Combined open risk',dailyAtRisk:'Realized loss plus combined risk',currency:'Currency',basis:'Paper specification source'};
    return`<details><summary>Deterministic paper arithmetic</summary><div class="ow-table-wrap"><table class="ow-table"><tbody>${Object.entries(metrics.risk).map(([k,v])=>`<tr><th scope="row">${esc(labels[k]||k)}</th><td>${v===null?'Unknown':typeof v==='number'?esc(fmt(v)):esc(v)}</td></tr>`).join('')}</tbody></table></div><p class="ow-hint">These calculations use the recorded inputs and paper specification. They do not forecast fills, gaps or outcomes and do not change execution behavior.</p></details>`;
  }
  function comparisonHTML(item){
    if(!comparisonVisible)return`<div class="ow-note"><h3>First pass complete · ARIA remained hidden</h3><p>The review above used your hypothesis and its frozen evidence. Reveal ARIA’s view only after you have considered the concerns yourself. Shared price facts are shared evidence, not independent confirmation.</p><button data-action="compare">Reveal comparison with ARIA</button></div>`;
    const c=item.comparison;
    if(!c)return'<p class="ow-note ow-warning">ARIA comparison is unavailable. The original structured review remains unchanged.</p>';
    const strings=(list,empty)=>list?.length?`<ul class="ow-fact-list">${list.map(findingHTML).join('')}</ul>`:`<p class="ow-muted">${empty}</p>`;
    return`<section class="ow-section"><h3>Then compare with ARIA</h3><p class="ow-hint">The candidate setup and the hypothesis review use different criteria. Agreement is allowed. Timeframe, method and freshness differences explain context; they do not establish two independent odds estimates.</p><h4>Facts agreed on</h4>${strings(c.factsAgreed,'No directly comparable fact was supplied.')}<h4>Interpretations that differ</h4>${strings(c.interpretationsDiffer,'No material interpretive difference identified on the shared evidence.')}<h4>Information still missing</h4>${strings(c.missing,'No additional comparison unknowns recorded.')}<p class="ow-hint">${(c.notes||[]).map(v=>esc(typeof v==='string'?v:v.fact||v.title)).join(' ')}</p><details><summary>Recorded ARIA context</summary><pre class="ow-json">${esc(JSON.stringify(item.aria,null,2))}</pre></details></section>`;
  }
  function renderReview(){
    const r=current(),item=activeReview();if(!r||!item){state.screen='history';return renderHistory();}
    const issueSummary=(title,list)=>!list?.length?'':`<section class="ow-issue"><h3>${title} · ${list.length}</h3><ul>${list.map(f=>`<li>${esc(typeof f==='string'?f:f.title||f.fact||f.id)}</li>`).join('')}</ul><details><summary>Why it matters</summary><ul class="ow-fact-list">${list.map(findingHTML).join('')}</ul></details></section>`;
    const h=item.hypothesis,s=item.snapshot,v=item.review,cls=v.assessment==='Supported on available evidence'?'ow-supported':v.assessment==='Material concern'?'ow-concern':'ow-insufficient';
    return`<div class="ow-context"><span class="ow-badge">${selectedReview<0?'Original first-pass review':`Reassessment ${selectedReview+1}`}</span><span class="ow-badge">${esc(METHODS[h.method]||h.method)} · ${esc(h.timeframe)}</span><span class="ow-badge">${esc(h.action==='wait'?'Deliberate wait':h.action+' paper idea')}</span></div><h2 id="owTitle">Review your plan</h2><p class="ow-hint">Saved ${esc(h.timeframe)} evidence · ${esc(when(s.asOf))}</p>${selectedReview>=0?`<section class="ow-diff"><h3>What changed since the previous review?</h3><ul>${(item.changes||[]).map(c=>`<li>${esc(c)}</li>`).join('')}</ul><p class="ow-hint">The earlier snapshot and explanation remain preserved. The new review applies the same declared hypothesis to newly captured evidence.</p></section>`:''}<div class="ow-assessment ${cls}"><div class="ow-eyebrow">Rule-based plan check</div><h2>${esc(v.assessment)}</h2><p>Checks your plan against its saved evidence. This is not a profit forecast.</p></div><details><summary>My recorded hypothesis</summary><p><strong>Observation:</strong> ${esc(h.observation)}</p><p><strong>Interpretation:</strong> ${esc(h.reasoning)}</p><p><strong>Invalidation:</strong> ${esc(h.invalidation.condition)} ${esc(fmt(h.invalidation.price))}. ${esc(h.invalidation.reason)}</p>${h.action==='wait'?`<p><strong>Wait:</strong> ${esc(h.wait.reason)} Revisit: ${esc(h.wait.condition)} at ${esc(fmt(h.wait.price))}.</p>`:`<p><strong>Paper plan:</strong> ${esc(h.action)}, entry ${esc(fmt(h.plan.entry))}, stop ${esc(fmt(h.plan.stop))}, target ${esc(fmt(h.plan.target))}, quantity ${esc(fmt(h.plan.quantity))}. Costs: ${esc(fmt(h.plan.cost))}.</p>`}</details>${issueSummary('Needs attention',v.constraints)}${issueSummary('Concerns',v.concerns)}${issueSummary('Limits to keep in mind',v.unknowns)}<section class="ow-section"><h3>Your next step</h3><p>Keep, revise or withdraw your idea. Explain the reason.</p>${item.decision?`<div class="ow-note"><strong>${esc({retain:'Retained',revise:'Revised',withdraw:'Withdrawn'}[item.decision.action]||item.decision.action)} · ${esc(when(item.decision.at))}</strong><p>${esc(item.decision.reason)}</p><p class="ow-hint">This reflection is retained with the original review.${item.decision.action==='revise'?' The revision is a separate linked hypothesis.':''}</p></div>`:`<label class="ow-field" for="ow-decision">My next step<select id="ow-decision" data-decision-field="action"><option value="retain" ${(item.decisionDraft?.action||'retain')==='retain'?'selected':''}>Retain the hypothesis</option><option value="revise" ${item.decisionDraft?.action==='revise'?'selected':''}>Revise it in a linked new record</option><option value="withdraw" ${item.decisionDraft?.action==='withdraw'?'selected':''}>Withdraw it / choose to wait</option></select></label><label class="ow-field" for="ow-reflection">What supports or changes your decision?<textarea id="ow-reflection" data-decision-field="reason" rows="3" maxlength="3000">${esc(item.decisionDraft?.reason||'')}</textarea><span class="ow-hint">At least 15 characters. Explain your judgment; agreeing with the reviewer is not required.</span></label><button class="ow-primary" data-action="decide">Save reflection</button>`}</section><details><summary>Previous review versions</summary><label class="ow-field" for="ow-review-version">Review version<select id="ow-review-version" data-review-version="true"><option value="-1" ${selectedReview===-1?'selected':''}>Original first pass · ${esc(when(r.snapshot.capturedAt||r.snapshot.asOf))} · ${esc(r.review.assessment)}</option>${r.reassessments.map((version,index)=>`<option value="${index}" ${selectedReview===index?'selected':''}>Reassessment ${index+1} · ${esc(when(version.snapshot.capturedAt||version.snapshot.asOf))} · ${esc(version.review.assessment)}</option>`).join('')}</select><span class="ow-hint">Inspect any saved evidence version and its own decision or reflection. Selecting a version does not refresh or rewrite it.</span></label></details><details><summary>Observed supporting facts</summary>${v.facts?.length?`<ul class="ow-fact-list">${v.facts.map(findingHTML).join('')}</ul>`:'<p>No supporting fact supplied.</p>'}</details>${metricHTML(v.metrics)}<details><summary>Captured chart &amp; sources</summary>${snapshotSummary(s)}${chart(s,h.timeframe)}${seriesSummary(s)}</details><section class="ow-section"><button data-action="changes" aria-expanded="${changeVisible}">${changeVisible?'Hide change conditions':'What would change this assessment?'}</button>${changeVisible?`<div class="ow-note"><p>These are observable review conditions, not trade signals or promises.</p>${v.whatChanges?.length?`<ul class="ow-fact-list">${v.whatChanges.map(findingHTML).join('')}</ul>`:'<p>No additional condition was supplied. Resolve the unknowns above and reread your thesis.</p>'}</div>`:''}</section><details><summary>Compare with ARIA</summary>${comparisonHTML(item)}</details>${v.limitations?.length?`<details><summary>What these checks can assess</summary><p class="ow-hint">${v.limitations.map(v=>esc(typeof v==='string'?v:v.fact||v.title)).join(' ')}</p></details>`:''}${error?`<p class="ow-error" role="alert">${esc(error)}</p>`:''}${busy?'<div class="ow-pending" role="status"><span class="ow-spinner"></span><span>Capturing new evidence. Your original review stays preserved.</span></div>':''}<div class="ow-actions"><button data-action="refresh" ${busy?'disabled':''}>Check with new evidence</button>${selectedReview>=0?'<button data-action="original">View original first pass</button>':''}<button data-action="history" data-section="plans">Back to plans</button><button data-action="new" ${busy?'disabled':''}>New plan</button><button class="ow-subtle" data-action="export">Export learning record</button></div><p class="ow-hint">Refresh captures evidence for ${esc(h.label)} using this record’s horizon and method, even if the workspace market has since changed.</p>`;
  }
  function unfinishedDraftsHTML(){
    const items=[state.draft,...state.savedDrafts].filter(Boolean);if(!items.length)return'';
    return `<section class="ow-section"><h3>Unfinished plans</h3><p class="ow-hint">Pick up where you left off. Your other drafts stay saved.</p><div class="ow-list">${items.map(d=>`<div class="ow-history-row"><div><strong>${esc(d.hypothesis.label)} · ${esc(d.hypothesis.timeframe)}</strong><small>${d===state.draft?'Current plan':'Retained plan'} · ${esc(STEPS[d.step])}${d.originReviewId?' · Linked to Oracle analysis':d.parentId?' · Linked revision':''}</small>${d.snapshot?`<small>Evidence cutoff ${esc(when(d.snapshot.asOf))}</small>`:''}</div><button data-action="${d===state.draft?'resume':'resume-saved'}" data-id="${esc(d.hypothesis.id)}">Resume plan</button></div>`).join('')}</div></section>`;
  }
  function renderDraftChoice(){
    if(!pendingDraft||!draft())return renderDraft();
    const next=pendingDraft,retained=state.savedDrafts.some(d=>d.hypothesis.id===next.hypothesis.id);
    const action=retained?'resume linked plan':next.parentId?'start linked revision':next.originReviewId?'start linked plan':'start new plan';
    return `<h2 id="owTitle">Keep your unfinished plan</h2><p>You have an unfinished plan for <strong>${esc(hypothesis().label)} · ${esc(hypothesis().timeframe)}</strong>. Its writing and frozen evidence are still intact.</p><p>The requested ${next.parentId?'revision':'plan'} is for <strong>${esc(next.hypothesis.label)} · ${esc(next.hypothesis.timeframe)}</strong>.${next.originReviewId?' Its saved Oracle analysis is already retained in the Journal.':''}</p><p>Continue the current plan, or keep it under Unfinished plans and switch. Both plans will remain in the browser record and export.</p><div class="ow-actions"><button class="ow-primary" data-action="resume">Resume existing plan</button><button data-action="keep-start">Keep existing &amp; ${action}</button><button data-action="export">Export learning records</button></div>`;
  }

  function paperTrades(){try{const trades=adapter.getTrades?.();return Array.isArray(trades)?clone(trades).sort((a,b)=>(b.closeTime||0)-(a.closeTime||0)):[];}catch(_){return[];}}
  function tradeKey(t){return JSON.stringify([String(t.id??''),String(t.sym||t.pair||''),t.openTime??null,t.closeTime??null]);}
  function tradeNote(t){return(state.tradeNotes||[]).find(n=>n.key===tradeKey(t));}
  const money=v=>typeof v==='number'&&Number.isFinite(v)?`${v<0?'−':v>0?'+':''}$${Math.abs(v).toFixed(2)}`:'Unavailable';
  const tradeTime=v=>v&&Number.isFinite(new Date(v).valueOf())?when(new Date(v).toISOString()):'Time unavailable';
  function homeTabs(){return`<nav class="ow-tabs" aria-label="Journal sections">${[['trades','Trades'],['plans','Plans'],['reviews','Saved reviews']].map(([key,label])=>`<button data-action="home-tab" data-section="${key}" aria-pressed="${homeTab===key}">${label}</button>`).join('')}</nav>`;}
  function tradeList(){
    const trades=paperTrades(),pending=trades.filter(t=>!tradeNote(t)?.text).length;
    return`<div class="ow-section-heading"><div><h3>Closed paper trades</h3><p class="ow-hint">Logged automatically when a paper position closes.</p></div><span class="ow-badge">${trades.length} logged</span></div>${trades.length?`<p class="ow-muted">${pending?`${pending} without a reflection`:'All trades have a reflection'}</p><div class="ow-list">${trades.map(t=>`<button class="ow-record" data-action="trade" data-id="${esc(tradeKey(t))}"><span><strong>${esc(t.pair||t.sym)}</strong><span class="ow-row-meta">${esc(String(t.type||'').toUpperCase())} · ${esc(t.volume)} lots · ${esc(tradeTime(t.closeTime))}</span><span class="ow-row-meta">${tradeNote(t)?.draftText!==undefined&&tradeNote(t).draftText!==tradeNote(t).text?'Reflection draft':tradeNote(t)?.text?'Reflection saved':'Add a reflection'}</span></span><span class="ow-record-end"><strong class="${Number.isFinite(t.pnl)?t.pnl<0?'ow-negative':'ow-positive':''}">${esc(money(t.pnl))}</strong><span>Review →</span></span></button>`).join('')}</div>`:'<div class="ow-empty"><h3>Your trades will appear here</h3><p>Close a paper position to see its prices and result, then add a short reflection.</p><button data-action="home-tab" data-section="plans">Plan an idea first</button></div>'}<p class="ow-hint ow-scope">Paper workspace history only. MT5 history remains in Portfolio.</p>`;
  }
  function plansList(){return`<div class="ow-section-heading"><div><h3>Your plans</h3><p class="ow-hint">Write an idea, check its logic, then reflect.</p></div><button class="ow-primary" data-action="new">New plan</button></div>${unfinishedDraftsHTML()}${state.records.length?`<h3>Saved plans</h3><div class="ow-list">${[...state.records].reverse().map(r=>`<button class="ow-record" data-action="view" data-id="${esc(r.id)}"><span><strong>${esc(r.hypothesis.label)} · ${esc(r.hypothesis.timeframe)}</strong><span class="ow-row-meta">${esc(r.hypothesis.action)} · ${esc(when((r.reassessments.at(-1)||r).snapshot.asOf))}</span><span class="ow-row-meta">${esc((r.reassessments.at(-1)||r).review.assessment)}</span><span class="ow-row-meta">${(r.reassessments.at(-1)||r).decision?'Reflection saved':'Reflection needed'}${r.parentId?' · Linked revision':''}</span></span><span class="ow-record-end">Review →</span></button>`).join('')}</div>`:!draft()&&!state.savedDrafts.length?'<div class="ow-empty">No plans yet. Start with a market you want to understand.</div>':''}`;}
  function renderHistory(){return`<h2 id="owTitle">Your journal</h2><p class="ow-muted">Log automatically. Reflect simply. Learn from each decision.</p>${homeTabs()}${homeTab==='trades'?tradeList():homeTab==='plans'?plansList():savedAnalysesHTML()}<details class="ow-backup"><summary>Back up your records</summary><p class="ow-hint">${esc(persistenceLabel())} This export contains paper trade history, trade reflections, plans, saved Oracle reviews and the last removal retained for Undo. Learn lesson records and MT5 history are separate.</p><button data-action="export">Export journal backup</button></details>`;}
  function renderTrade(){
    const t=paperTrades().find(t=>tradeKey(t)===selectedTradeKey);if(!t)return`<h2 id="owTitle">Trade unavailable</h2><p>This trade is no longer in the paper history. Saved reflections remain in the journal backup.</p><button data-action="history">Back to trades</button>`;
    const note=tradeNote(t);
    return`<button class="ow-back" data-action="history" data-section="trades">← All trades</button><div class="ow-detail-title"><div><span class="ow-eyebrow">Closed paper trade</span><h2 id="owTitle">${esc(t.pair||t.sym)}</h2><p class="ow-muted">${esc(String(t.type||'').toUpperCase())} · ${esc(t.volume)} lots</p></div><strong class="ow-trade-result ${Number.isFinite(t.pnl)?t.pnl<0?'ow-negative':'ow-positive':''}">${esc(money(t.pnl))}</strong></div><div class="ow-trade-prices"><div><span>Entry</span><strong>${esc(fmt(t.entry))}</strong></div><div><span>Exit</span><strong>${esc(fmt(t.exit))}</strong></div><div><span>Closed</span><strong>${esc(tradeTime(t.closeTime))}</strong></div></div><label class="ow-field" for="ow-trade-reflection">What would you repeat or change?<textarea id="ow-trade-reflection" data-trade-note rows="4" maxlength="3000" placeholder="One useful takeaway is enough.">${esc(note?.draftText??note?.text??'')}</textarea><span class="ow-hint">Optional. The trade is already logged; this is your reflection.</span></label><button class="ow-primary" data-action="save-trade-note">Save reflection</button><p id="owNoteStatus" class="ow-status-line" role="status">${esc(noteStatus|| (warning?'Saving is unavailable; keep this tab open.':note?.draftText!==undefined&&note.draftText!==note.text?'Draft saved — finish when ready.':note?.text?'Reflection saved.':''))}</p><details><summary>Trade details</summary><dl class="ow-trade-facts"><dt>Opened</dt><dd>${esc(tradeTime(t.openTime))}</dd><dt>Closed by</dt><dd>${esc(t.reason||'Manual')}</dd><dt>Ticket</dt><dd>${esc(t.id)}</dd></dl></details>`;
  }
  function updateTradeNote(value,commit=false){
    const t=paperTrades().find(t=>tradeKey(t)===selectedTradeKey);if(!t)return;
    const key=tradeKey(t),previous=tradeNote(t),text=String(value).slice(0,3000);
    if(commit&&!text.trim()){noteStatus='Write a takeaway before saving.';render();return;}
    const next={key,text:commit?text.trim():previous?.text||'',draftText:commit?text.trim():text,updatedAt:new Date().toISOString()};
    const candidate={...state,updatedAt:new Date().toISOString(),tradeNotes:[...(state.tradeNotes||[]).filter(n=>n.key!==key),next]};
    if(commit){
      const failure=storageReadable?writeState(storage,candidate):'Browser records are unavailable. Keep this tab open and export a backup.';
      if(failure){warning=failure;noteStatus='Could not save. Your draft is still here.';render();return;}
      state.tradeNotes=candidate.tradeNotes;state.updatedAt=candidate.updatedAt;warning='';noteStatus='Reflection saved.';renderPanel();render();return;
    }
    state.tradeNotes=candidate.tradeNotes;save();
    noteStatus=warning?'Draft not saved. Keep this tab open.':next.draftText===next.text?'Reflection saved.':'Draft saved — finish when ready.';
    const status=doc.getElementById('owNoteStatus');if(status)status.textContent=noteStatus;
  }

  function render(){
    if(!dialog?.open)return;
    const scroll=dialog.querySelector?.('.ow-body')?.scrollTop||0;
    dialog.innerHTML=`<div class="ow-head"><div><strong>Journal</strong></div><button class="ow-close" data-action="close" aria-label="Close Journal review workspace">×</button></div><div class="ow-body">${state.screen==='trade'?renderTrade():state.screen==='draft-choice'?renderDraftChoice():state.screen==='history'?renderHistory():state.screen==='analysis'?renderSavedAnalysis():state.screen==='review'?renderReview():renderDraft()}</div><div id="owSave" class="ow-foot" role="status" aria-live="polite"></div>`;
    const status=doc.getElementById('owSave');status.textContent=warning||persistenceLabel();status.classList.toggle('ow-warning',!!warning);
    const body=dialog.querySelector?.('.ow-body');if(body)body.scrollTop=scroll;
  }
  function focusTitle(){dialog.scrollTop=0;const body=dialog.querySelector?.('.ow-body');if(body)body.scrollTop=0;const title=doc.getElementById('owTitle');if(title){title.tabIndex=-1;title.focus({preventScroll:true});dialog.scrollTop=0;}}

  function renderPanel(){
    if(!doc||!state)return;const panel=doc.getElementById('journal-learning-panel');if(!panel)return;
    panel.innerHTML=`<div class="ow-launch"><h3>Your journal</h3><p>Trades, plans and saved Oracle reviews in one place.</p><div class="ow-launch-stats"><span><strong>${paperTrades().length}</strong>Trades</span><span><strong>${state.records.length+[state.draft,...state.savedDrafts].filter(Boolean).length}</strong>Plans</span><span><strong>${state.savedAnalyses.length}</strong>Saved reviews</span></div><button class="ow-primary" data-ow-home>Open journal</button>${draft()?`<button data-ow-resume>Continue ${esc(hypothesis().label)} plan</button>`:''}<p class="ow-hint">Paper trades log automatically. ${esc(persistenceLabel())}</p></div>`;
    panel.querySelector('[data-ow-home]').onclick=()=>open({history:true});const resume=panel.querySelector('[data-ow-resume]');if(resume)resume.onclick=()=>{resumeDraft();open();};
  }
  function resumeDraft(){
    pendingDraft=null;state.screen='draft';state.selectedId=null;selectedReview=-1;error='';save();render();focusTitle();
  }
  function activateDraft(next){
    // One persisted state change retains the outgoing draft before switching.
    request++;controller?.abort();busy=false;
    const old=draft(),nextId=next.hypothesis.id;
    state.savedDrafts=state.savedDrafts.filter(d=>d.hypothesis.id!==nextId&&d.hypothesis.id!==old?.hypothesis.id);
    if(old&&old.hypothesis.id!==nextId)state.savedDrafts.push(clone(old));
    state.draft=clone(next);resumeDraft();
  }
  function requestDraft(next){
    const origin=next.originReviewId;
    if(draft()&&(draft().hypothesis.id===next.hypothesis.id||origin&&draft().originReviewId===origin)){resumeDraft();return;}
    if(origin)next=state.savedDrafts.find(d=>d.originReviewId===origin)||next;
    if(!draft()){activateDraft(next);return;}
    pendingDraft=clone(next);state.screen='draft-choice';error='';render();focusTitle();
  }
  function newDraft({from=null,parentId=null,lessonLink=null}={}){
    const context=from?{...safeContext(),symbol:from.symbol,label:from.label,timeframe:from.timeframe}:safeContext();
    if(!context.symbol){error='Select a supported instrument in the workspace first.';state.screen='draft';render();return;}
    requestDraft({context:clone(context),hypothesis:from?{...clone(from),id:id()}:makeHypothesis(context),snapshot:null,step:0,parentId,lessonRef:lessonLink||context.lessonRef||null});
  }
  function draftFromAnalysis(saved){
    const s=saved.snapshot,timeframe=s.profile==='intraday-v1'?'15m':saved.analysis.timeframe||saved.analysis.primaryTimeframe||Object.keys(s.series||{}).find(tf=>HIGHER[tf])||'15m';
    const context={symbol:s.symbol,label:s.label||s.symbol,timeframe:HIGHER[timeframe]?timeframe:'15m',supportedTimeframes:Object.keys(HIGHER),provider:s.provider,account:s.account||{},spec:s.spec||null,lessonRef:saved.lessonRef||null};
    requestDraft({context,hypothesis:makeHypothesis(context),snapshot:clone(s),step:1,parentId:null,originReviewId:saved.id,originAnalysis:clone({...saved.analysis,marketReview:saved.marketReview||null}),lessonRef:saved.lessonRef||null});
  }
  function analysisSummary(analysis){
    const summary=analysis.summary||analysis.marketSummary||analysis.headline||analysis.assessment||analysis.title||'Captured market analysis';
    return typeof summary==='string'?summary:Array.isArray(summary)?summary.map(v=>typeof v==='string'?v:object(v)?v.title||v.fact||v.text||'':'').join(' '):JSON.stringify(summary);
  }

  function reviewRemovalStatus(){
    const trash=state.reviewTrash;
    return `${reviewNotice?`<p class="ow-removal-message ${reviewNoticeError?'ow-error':''}" role="${reviewNoticeError?'alert':'status'}">${esc(reviewNotice)}</p>`:''}${trash?`<div class="ow-review-undo"><div><strong>${trash.items.length} ${trash.items.length===1?'review removed':'reviews removed'}</strong><p>Undo restores the last removal, even after reload. Your next removal replaces this Undo.</p></div><button data-action="undo-analyses" ${busy?'disabled':''}>Undo</button></div>`:''}`;
  }
  function commitReviewChange(next,message){
    if(!storageReadable){reviewNotice='Saved records could not be read safely. Nothing was changed; export a backup before continuing.';reviewNoticeError=true;render();return false;}
    try{if(!storage||storage.getItem(KEY)!==storageBaseline){reviewNotice='Journal changed in another tab. Nothing was changed here; reload to see the latest records before trying again.';reviewNoticeError=true;render();return false;}}
    catch(_){reviewNotice='Journal storage is unavailable. Nothing was changed; try again when storage is available.';reviewNoticeError=true;render();return false;}
    next.updatedAt=new Date().toISOString();const failure=writeState(storage,next);
    if(failure){warning=failure;reviewNotice='Could not save this change. Your saved reviews and Undo are unchanged.';reviewNoticeError=true;render();return false;}
    state=next;warning='';reviewNotice=message;reviewNoticeError=false;homeTab='reviews';renderPanel();render();focusTitle();return true;
  }
  function removeAnalyses(reviewId){
    if(busy||reviewId!==null&&(typeof reviewId!=='string'||!reviewId))return;
    const before=state,list=state.savedAnalyses||[],items=list.map((review,index)=>({index,review})).filter(item=>reviewId===null||item.review.id===reviewId);
    if(!items.length)return;
    if(typeof root.confirm!=='function'){reviewNotice='Confirmation is unavailable. No saved reviews were removed.';reviewNoticeError=true;render();return;}
    const label=reviewId===null?`Clear all ${items.length} saved ${items.length===1?'review':'reviews'}?`:`Delete the saved review for ${items[0].review.snapshot.label||items[0].review.snapshot.symbol} (${when(items[0].review.savedAt)})?`;
    const message=label+'\n\nThis removes only these Journal saved reviews. Trades, plans, reflections and Oracle conversations stay intact.\n\nUndo restores this removal, even after reload. The next removal replaces Undo.'+(state.reviewTrash?'\n\nThis replaces your previous Undo; those previously removed reviews will no longer be recoverable here.':'');
    if(!root.confirm(message)||state!==before||busy)return;
    const ids=new Set(items.map(item=>item.review.id));
    commitReviewChange({...state,savedAnalyses:list.filter(a=>!ids.has(a.id)),reviewTrash:{removedAt:new Date().toISOString(),items:clone(items)},selectedAnalysisId:null,screen:'history'},`${items.length===1?'Saved review removed.':items.length+' saved reviews removed.'} You can undo this below.`);
  }
  function undoAnalyses(){
    if(busy||!state.reviewTrash)return;
    const saved=[...state.savedAnalyses],ids=new Set(saved.map(a=>a.id));let restored=0;
    for(const item of [...state.reviewTrash.items].sort((a,b)=>a.index-b.index)){
      if(ids.has(item.review.id))continue;
      saved.splice(Math.min(item.index,saved.length),0,clone(item.review));ids.add(item.review.id);restored++;
    }
    commitReviewChange({...state,savedAnalyses:saved,reviewTrash:null,selectedAnalysisId:null,screen:'history'},restored?`${restored} saved ${restored===1?'review restored':'reviews restored'}.`:'These reviews are already saved. The existing copies were kept.');
  }
  function savedAnalysesHTML(){
    const list=state.savedAnalyses||[];
    return`<div class="ow-section-heading"><div><h3>Saved Oracle reviews</h3><p class="ow-hint">Market readings and conversations you chose to keep.</p></div><span class="ow-badge">${list.length} saved</span></div>${reviewRemovalStatus()}${list.length?`<div class="ow-review-toolbar"><button class="ow-delete" data-action="clear-analyses" ${busy?'disabled':''}>Clear saved reviews</button></div><div class="ow-list">${[...list].reverse().map(a=>`<article class="ow-saved-review"><button class="ow-record" data-action="read-analysis" data-id="${esc(a.id)}"><span><strong>${esc(a.snapshot.label||a.snapshot.symbol)} · ${esc(a.analysis.timeframe||a.analysis.primaryTimeframe||'Saved reading')}</strong><span class="ow-row-meta">${esc(when(a.savedAt))}</span><span class="ow-row-preview">${esc(a.marketReview?.reading||analysisSummary(a.analysis))}</span></span><span class="ow-record-end">Read →</span></button><div class="ow-review-row-actions"><button class="ow-delete" data-action="delete-analysis" data-id="${esc(a.id)}" aria-label="Delete saved review for ${esc(a.snapshot.label||a.snapshot.symbol)} · ${esc(when(a.savedAt))}" ${busy?'disabled':''}>Delete review</button></div></article>`).join('')}</div>`:'<div class="ow-empty">No saved reviews. In Oracle, choose “Save review only” to keep a reading here.</div>'}`;
  }
  function renderSavedAnalysis(){
    const saved=(state.savedAnalyses||[]).find(a=>a.id===state.selectedAnalysisId);if(!saved)return renderHistory();
    const a=saved.analysis,parts=(title,items)=>Array.isArray(items)&&items.length?`<section class="ow-section"><h3>${title}</h3><ul class="ow-fact-list">${items.filter(item=>typeof item==='string'||object(item)).map(item=>typeof item==='string'?`<li class="ow-item">${esc(item)}</li>`:`<li class="ow-item">${item.title?`<h4>${esc(item.title)}</h4>`:''}${item.fact?`<p>${esc(item.fact)}</p>`:''}${item.relevance?`<p class="ow-muted">Why it matters: ${esc(item.relevance)}</p>`:''}${item.resolution?`<p>Revisit if: ${esc(item.resolution)}</p>`:''}</li>`).join('')}</ul></section>`:'';
    return `<div class="ow-eyebrow">Journal · Saved Oracle analysis</div><h2 id="owTitle">${esc(saved.snapshot.label||saved.snapshot.symbol)} · ${esc(a.timeframe||'Captured horizon')}</h2><p class="ow-hint">Saved ${esc(when(saved.savedAt))}</p><div class="ow-actions"><button class="ow-primary" data-action="add-plan" data-id="${esc(saved.id)}">Add my plan</button><button data-action="history" data-section="reviews">All saved reviews</button><button class="ow-delete" data-action="delete-analysis" data-id="${esc(saved.id)}" ${busy?'disabled':''}>Delete review</button></div>${reviewRemovalStatus()}${marketReviewHTML(saved)}<details><summary>Calculated facts &amp; evidence</summary>${snapshotSummary(saved.snapshot)}<div class="ow-note"><h3>Calculated market facts</h3><strong>${esc(a.status||'Retained analysis')}</strong><p>${esc(analysisSummary(a))}</p><p class="ow-hint">${esc(a.method||'Retained source analysis; read its method and limitations.')}</p></div>${parts('Observed market facts',a.facts)}${parts('Alternative interpretations',a.alternatives)}${parts('What could change this reading?',a.whatChanges)}${parts('Unknown or unassessed context',a.unknowns)}</details>${saved.questions?.length?`<details><summary>Retained conversation and questions</summary>${saved.questions.filter(q=>typeof q==='string'||object(q)).map(q=>`<div class="ow-item"><strong>${esc(typeof q==='string'?q:(q.role==='assistant'?'Oracle · live agent':q.question||q.text))}</strong>${object(q)?`<p>${esc(q.role==='assistant'?q.text:q.illustrativeResponse||q.response||'')}</p><p class="ow-hint">${esc(q.label||(q.pending?'Saved question · no live reply generated':q.role==='assistant'?'Reply from the connected private agent.':'Question retained with the market evidence.'))}</p>`:''}</div>`).join('')}</details>`:''}<details><summary>Inspect the retained chart and sources</summary>${chart(saved.snapshot,saved.snapshot.series[a.timeframe]?a.timeframe:Object.keys(saved.snapshot.series)[0])}${seriesSummary(saved.snapshot)}</details>`;
  }
  async function capture(h){
    const seq=++request;controller?.abort();controller=new AbortController();busy=true;error='';render();
    try{const s=await adapter.captureSnapshot(clone(h),{signal:controller.signal});if(seq!==request||controller.signal.aborted)return null;if(!s||s.symbol!==h.symbol)throw Error('The evidence belongs to another market. Capture again before reviewing.');return clone(s);}
    catch(e){if(seq===request&&!controller.signal.aborted)error=e?.message||'Market evidence could not be captured. Check the connection and try again. No review was invented.';return null;}
    finally{if(seq===request){busy=false;render();}}
  }
  async function next(){
    if(busy||!draft())return;error=validateHypothesis(hypothesis(),draft().step);if(error){render();return;}
    if(draft().step===0){const h=clone(hypothesis()),s=await capture(h);if(!s||!draft()||draft().hypothesis.id!==h.id)return;draft().snapshot=s;draft().step=1;}
    else if(draft().step===1)draft().step=2;
    else{
      try{
        const h=clone(hypothesis()),s=clone(draft().snapshot),review=clone(root.ProTraderOracle.review(h,s));
        // ARIA is captured only after the pure first pass has finished. It is
        // retained on the same evidence, then withheld visually until requested.
        let aria=null,comparison=null;try{aria=clone(adapter.captureAria(s,h));comparison=clone(adapter.compare(review,h,s,aria));}catch(e){comparison={factsAgreed:[],interpretationsDiffer:[],missing:['ARIA comparison unavailable: '+(e?.message||'Could not calculate the comparison.')],notes:[]};}
        const record=createRecord({parentId:draft().parentId,originReviewId:draft().originReviewId,originAnalysis:draft().originAnalysis,lessonRef:draft().lessonRef,hypothesis:h,snapshot:s,review,aria,comparison});
        state.records.push(record);state.selectedId=record.id;state.draft=null;state.screen='review';selectedReview=-1;comparisonVisible=false;changeVisible=false;
      }catch(e){error=e?.message||'The structured review could not run. Your hypothesis draft remains available.';render();return;}
    }
    save();render();focusTitle();
  }
  async function refresh(){
    if(busy||!current())return;const recordId=current().id,previous=activeReview(),h=clone(previous.hypothesis),s=await capture(h);if(!s||current()?.id!==recordId)return;
    try{
      const review=clone(root.ProTraderOracle.review(h,s));let aria=null,comparison=null;
      try{aria=clone(adapter.captureAria(s,h));comparison=clone(adapter.compare(review,h,s,aria));}catch(e){comparison={factsAgreed:[],interpretationsDiffer:[],missing:['ARIA comparison unavailable: '+(e?.message||'Unknown error')],notes:[]};}
      const changes=snapshotChanges(previous.snapshot,s);if(review.assessment!==previous.review.assessment)changes.push(`Assessment changed: ${previous.review.assessment} → ${review.assessment}.`);else changes.push(`Assessment remains: ${review.assessment}.`);
      const updated=appendReassessment(current(),{hypothesis:h,snapshot:s,review,aria,comparison,changes});state.records[state.records.findIndex(r=>r.id===recordId)]=updated;selectedReview=current().reassessments.length-1;comparisonVisible=false;changeVisible=true;save();render();focusTitle();
    }catch(e){error=e?.message||'New review could not run. The original learning record remains preserved.';render();}
  }
  function decide(){
    const r=current(),item=activeReview();if(!r||!item||item.decision)return;const action=doc.getElementById('ow-decision').value,reason=doc.getElementById('ow-reflection').value.trim();
    if(reason.length<15){error='Explain your decision using at least 15 characters. Evidence and judgment matter more than agreement with the reviewer.';render();return;}
    const reviewHypothesis=clone(item.hypothesis),decision={action,reason,reviewSnapshotId:item.snapshot.id};
    state.records[state.records.findIndex(v=>v.id===r.id)]=selectedReview>=0?decideReassessment(r,selectedReview,decision):decideRecord(r,decision);save();
    if(action==='revise'){newDraft({from:reviewHypothesis,parentId:r.id,lessonLink:r.lessonRef});return;}
    error='';render();
  }
  function download(){const blob=new Blob([JSON.stringify({...exportRecord(state),paperTrades:paperTrades(),scope:'Paper trades, trade reflections, plans and saved Oracle reviews. Excludes Learn lesson records and MT5 history.'},null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=doc.createElement('a');a.href=url;a.download='protrader-journal-backup.json';doc.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  function close(){request++;controller?.abort();busy=false;pendingDraft=null;if(state?.screen==='draft-choice')state.screen='draft';dialog?.close();returnFocus?.focus?.();}
  function open(options={}){
    if(!dialog||accountChanging)return;returnFocus=doc.activeElement;pendingDraft=null;
    if(options.snapshot&&options.analysis){const saved=saveAnalysis({id:options.originReviewId||options.analysis.id,snapshot:options.snapshot,analysis:options.analysis,questions:options.questions,lessonRef:options.lessonLink});draftFromAnalysis(saved);}
    else if(options.savedAnalysisId){state.selectedAnalysisId=options.savedAnalysisId;state.screen='analysis';}
    else if(options.originReviewId){const saved=(state.savedAnalyses||[]).find(a=>a.id===options.originReviewId);if(saved)draftFromAnalysis(saved);else{error='That saved analysis is unavailable in this browser.';state.screen='history';}}
    else if(options.history){state.screen='history';homeTab=options.section||'trades';}else if(!draft()&&state.screen!=='review')newDraft({lessonLink:options.lessonLink});
    else if(options.lessonLink&&draft())draft().lessonRef=options.lessonLink;
    if(!dialog.open)dialog.showModal();render();focusTitle();
  }
  function clearForAccountChange(){
    // Stop captures before ACCOUNT replaces its local document set. Never save
    // blank state into either the departing or incoming person's records.
    accountChanging=true;request++;controller?.abort();controller=null;busy=false;
    dialog?.close();pendingDraft=null;returnFocus=null;selectedReview=-1;
    comparisonVisible=false;changeVisible=false;selectedTradeKey=null;
    state=blankState();storageReadable=false;storageBaseline=null;
    error='';warning='Changing account…';noteStatus='';reviewNotice='';reviewNoticeError=false;
    if(dialog)dialog.innerHTML='';renderPanel();
  }
  function reloadStorage(){
    clearForAccountChange();
    try{storage=root.localStorage;}catch(_){storage=null;}
    const loaded=readState(storage);state=loaded.state;warning=loaded.warning;
    storageReadable=loaded.readable??!warning;
    try{storageBaseline=storage?.getItem(KEY)??null;}catch(_){storageReadable=false;}
    accountChanging=false;homeTab='trades';renderPanel();
  }
  function mount(documentRef,adapterRef){
    if(doc){adapter=adapterRef||adapter;renderPanel();return;}
    doc=documentRef;adapter=adapterRef;
    try{storage=root.localStorage;}catch(_){storage=null;}
    const loaded=readState(storage);state=loaded.state;warning=loaded.warning;storageReadable=loaded.readable??!warning;try{storageBaseline=storage?.getItem(KEY)??null;}catch(_){storageReadable=false;}
    dialog=doc.createElement('dialog');dialog.id='oracleWorkspaceDialog';dialog.className='ow-dialog';dialog.setAttribute('aria-labelledby','owTitle');doc.body.appendChild(dialog);
    dialog.addEventListener('keydown',event=>event.stopPropagation());
    dialog.addEventListener('cancel',()=>{request++;controller?.abort();busy=false;pendingDraft=null;if(state.screen==='draft-choice')state.screen='draft';});
    dialog.addEventListener('input',event=>{
      if(accountChanging)return;
      const el=event.target;if(el.dataset.tradeNote!==undefined){updateTradeNote(el.value);return;}if(el.dataset.decisionField&&activeReview()&&!activeReview().decision){const item=activeReview();item.decisionDraft=item.decisionDraft||{action:'retain',reason:''};item.decisionDraft[el.dataset.decisionField]=el.value;save();return;}if(!el.dataset.field||!hypothesis())return;
      setPath(hypothesis(),el.dataset.field,el.type==='number'?number(el.value):el.value);save();
    });
    dialog.addEventListener('change',event=>{
      if(accountChanging)return;
      const el=event.target;if(el.dataset.reviewVersion!==undefined){const index=Number(el.value);if(current()&&Number.isInteger(index)&&index>=-1&&index<current().reassessments.length){selectedReview=index;comparisonVisible=false;changeVisible=false;error='';render();focusTitle();}return;}if(el.dataset.decisionField&&activeReview()&&!activeReview().decision){const item=activeReview();item.decisionDraft=item.decisionDraft||{action:'retain',reason:''};item.decisionDraft[el.dataset.decisionField]=el.value;save();return;}if(!el.dataset.field||!hypothesis())return;
      setPath(hypothesis(),el.dataset.field,el.type==='number'?number(el.value):el.value);
      if(el.dataset.field==='action'||el.dataset.field==='timeframe'||el.dataset.field==='method'){save();render();}else save();
    });
    dialog.addEventListener('click',event=>{
      if(accountChanging)return;
      const button=event.target.closest('[data-action]');if(!button||button.disabled)return;const action=button.dataset.action;
      if(action==='close')close();else if(action==='next')next();else if(action==='back'&&!busy){draft().step--;error='';save();render();focusTitle();}
      else if(action==='delete-analysis')removeAnalyses(button.dataset.id);
      else if(action==='clear-analyses')removeAnalyses(null);
      else if(action==='undo-analyses')undoAnalyses();
      else if(action==='read-analysis'){state.selectedAnalysisId=button.dataset.id;state.screen='analysis';render();focusTitle();}
      else if(action==='add-plan'&&!busy){const saved=(state.savedAnalyses||[]).find(a=>a.id===button.dataset.id);if(saved)draftFromAnalysis(saved);}
      else if(action==='new'&&!busy)newDraft();else if(action==='history'||action==='home-tab'){homeTab=button.dataset.section||homeTab;state.screen='history';error='';render();focusTitle();}
      else if(action==='trade'){selectedTradeKey=button.dataset.id;noteStatus='';state.screen='trade';render();focusTitle();}
      else if(action==='save-trade-note')updateTradeNote(doc.getElementById('ow-trade-reflection').value,true);
      else if(action==='resume')resumeDraft();
      else if(action==='keep-start'&&pendingDraft)activateDraft(pendingDraft);
      else if(action==='resume-saved'&&!busy){const saved=state.savedDrafts.find(d=>d.hypothesis.id===button.dataset.id);if(saved)activateDraft(saved);}
      else if(action==='view'){state.selectedId=button.dataset.id;state.screen='review';selectedReview=(current()?.reassessments.length||0)-1;comparisonVisible=false;changeVisible=false;error='';save();render();focusTitle();}
      else if(action==='compare'){comparisonVisible=true;render();}else if(action==='changes'){changeVisible=!changeVisible;render();}
      else if(action==='refresh')refresh();else if(action==='original'){selectedReview=-1;comparisonVisible=false;changeVisible=false;render();focusTitle();}
      else if(action==='decide')decide();else if(action==='export')download();
    });
    renderPanel();
  }
  return{mount,renderPanel,open,openSavedAnalysis:id=>open({savedAnalysisId:id}),close,clearForAccountChange,reloadStorage,importAnalysis,saveAnalysis,readState,writeState,exportRecord,makeHypothesis,createRecord,appendReassessment,decideRecord,decideReassessment,validateHypothesis,snapshotChanges,tradeKey,storageKey:KEY,getState:()=>state?clone(state):null};
});
