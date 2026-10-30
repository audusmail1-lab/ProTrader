/* Actual closed-OHLC summaries with an explicit private conversation connection. */
(function(root,factory){const api=factory(root);if(typeof module==='object'&&module.exports)module.exports=api;else root.OracleAnalyst=api;})(typeof window==='undefined'?globalThis:window,function(root){
  'use strict';
  const KEY='protrader.oracle.analyst-preview.v1',SECONDS={'1m':60,'5m':300,'15m':900,'1h':3600,'4h':14400,'1d':86400};
  const HIGHER={'1m':'15m','5m':'1h','15m':'1h','1h':'4h','4h':'1d'};
  const INTRADAY=['4h','1h','15m','5m'],ROLES={'4h':'Context','1h':'Active structure','15m':'Setup','5m':'Timing'};
  const isMTF=s=>s?.profile==='intraday-v1';
  const horizons=a=>a?.profile==='intraday-v1'?'Intraday · 4H → 1H → 15m → 5m':`${a?.timeframe} + ${a?.higherTimeframe}`;
  const clone=v=>JSON.parse(JSON.stringify(v));
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const fmt=n=>typeof n==='number'&&Number.isFinite(n)?n.toLocaleString(undefined,{maximumFractionDigits:5}):'Unavailable';
  const when=n=>new Date(n*1000).toLocaleString();
  const cutoff=n=>new Date(n*1000).toLocaleString(undefined,{timeZoneName:'short'});
  function analyze(snapshot,timeframe){
    const a={version:1,id:'read-'+snapshot.id,timeframe,higherTimeframe:HIGHER[timeframe],title:'A read of the available market evidence',
      method:'Transparent OHLC summary; actual market data, not conversational AI',status:'Insufficient information',summary:'',facts:[],alternatives:[],whatChanges:[],unknowns:[],metrics:{}};
    const evidence=root.OracleEvidence?.extract(snapshot,timeframe);
    if(!evidence)a.unknowns.push('The validated evidence reader is unavailable; reload the preview.');
    for(const u of evidence?.unknowns||[])a.unknowns.push(`${u.timeframe||'Snapshot'}: ${u.message}`);
    if(isMTF(snapshot)){a.profile='intraday-v1';a.version=2;a.higherTimeframe=null;}
    for(const tf of isMTF(snapshot)?INTRADAY:[timeframe,HIGHER[timeframe]]){
      const f=evidence?.frames[tf];if(!f)continue;
      a.metrics[tf]={close:f.lastClose,low:f.prior20Low,high:f.prior20High,displacement:f.closeDisplacement20,closedAt:f.closedAt,bars:f.closedBars,...(f.structure?{structure:clone(f.structure)}:{})};
      a.facts.push({title:`${tf} · completed price action`,fact:`Last close ${fmt(f.lastClose)}. Prior 20-bar low/high ${fmt(f.prior20Low)} / ${fmt(f.prior20High)}. The last 20 closes ${f.closeDisplacement20>0?'rose':f.closeDisplacement20<0?'fell':'were unchanged by'} ${fmt(Math.abs(f.closeDisplacement20))}.`,relevance:'Observed prices and bounds describe this sample; they do not establish the next direction.',ref:f.refs[0]});
    }
    const p=a.metrics[timeframe],h=a.metrics[HIGHER[timeframe]];
    if(p){
      a.summary=`${snapshot.label||snapshot.symbol} closed at ${fmt(p.close)} on ${timeframe}. ${p.close>p.high?'That close is above':p.close<p.low?'That close is below':'It remains inside'} the prior 20-bar ${fmt(p.low)}–${fmt(p.high)} price range.`;
      if(h)a.summary+=` On ${a.higherTimeframe}, the last 20 closes ${h.displacement>0?'rose':h.displacement<0?'fell':'were unchanged by'} ${fmt(Math.abs(h.displacement))}.`;
      a.alternatives.push({title:'An alternative reading',fact:h&&Math.sign(p.displacement)!==Math.sign(h.displacement)?`${timeframe} and ${a.higherTimeframe} close displacement differ in direction.`:'A recent move can be part of a broader range; these candles do not establish whether it will continue.',relevance:'A pullback, continuation and range interpretation can require different horizons and entry conditions. Neither more indicators nor a single bar settles that choice.',resolution:`Compare the saved ${a.higherTimeframe} context with the next completed ${timeframe} close; state which method you are testing.`});
      a.whatChanges.push({fact:`The saved ${timeframe} reference range is ${fmt(p.low)}–${fmt(p.high)}.`,resolution:`A new completed ${timeframe} close beyond either observed bound, a changed ${a.higherTimeframe} context, or corrected/missing data would justify a new read. It would not automatically authorize an entry.`});
    }else a.summary='There is not enough verified, recent completed-candle evidence for this market read.';
    if(isMTF(snapshot)){
      a.status=evidence?.available?'Data available':'Insufficient information';
      a.interpretation=root.OracleEvidence?.interpret(evidence);
      a.method='Calculated structure read · completed candles · intraday-structure-hierarchy-v1; separate from connected AI interpretation';
      a.summary=a.interpretation?.reading||'The automatic structure reader is unavailable. Reload to reassess the saved evidence.';
      a.alternatives=[{fact:'A lower-timeframe move against the broader structure may be a pullback, a range or a reversal attempt.',relevance:'The hierarchy is an intraday review profile. Directional disagreement alone does not decide which interpretation fits.'}];
      a.whatChanges=[{resolution:a.interpretation?`${a.interpretation.setupInvalidation} ${a.interpretation.contextInvalidation}`:'Capture new completed candles to reassess the setup and higher context separately. A failed 5m trigger does not by itself invalidate the 4h structure.'}];
      a.unknowns.push('Confirmed swings use two completed bars on each side, within at most 120 bars per timeframe. Confirmation lags price; the sample may not contain two usable highs and lows. A 20-bar range spans different elapsed time on each frame.');
    }else a.status=p&&h?'Data available':'Insufficient information';
    a.unknowns.push('News, macro events, order flow, hidden liquidity, broker fills and validated edge are not assessed by these candle sources.');
    return a;
  }
  const MAX_HISTORY=8,MAX_MESSAGES=40,REVIEW_FIELDS=['reading','support','concern','whatChanges','limits'];
  function mtfFields(value){
    const prose=v=>typeof v==='string'&&v.trim().length>=4&&v.length<=700;
    const keys=['governing','setupCondition','setupInvalidation','contextInvalidation'];
    if(!value||value.profile!=='intraday-v1'||!['aligned','compatible-pullback','conflicting','mixed','undetermined','incomplete'].includes(value.relationship)||!keys.every(k=>prose(value[k]))||!Array.isArray(value.frames)||value.frames.length!==4)return null;
    if(!INTRADAY.every(tf=>value.frames.filter(f=>f?.timeframe===tf&&prose(f.reading)&&prose(f.evidence)).length===1))return null;
    return {profile:'intraday-v1',relationship:value.relationship,...Object.fromEntries(keys.map(k=>[k,value[k].trim()])),frames:INTRADAY.map(tf=>{const f=value.frames.find(f=>f.timeframe===tf);return{timeframe:tf,reading:f.reading.trim(),evidence:f.evidence.trim(),...(['bullish','bearish','mixed','undetermined'].includes(f.bias)?{bias:f.bias}:{})};})};
  }
  function reviewFields(value,requireMTF=false){
    if(!value||typeof value!=='object'||!REVIEW_FIELDS.every(k=>typeof value[k]==='string'&&value[k].trim().length>=8&&value[k].length<=1800))return null;
    const mtf=requireMTF?mtfFields(value.mtf):null;if(requireMTF&&!mtf)return null;
    return {...Object.fromEntries(REVIEW_FIELDS.map(k=>[k,value[k].trim()])),...(mtf?{mtf}:{})};
  }
  function parseReview(text){try{const value=JSON.parse(text.trim().replace(/^```(?:json)?\s*/i,'').replace(/\s*```$/,''));const fields=reviewFields(value,isMTF(packet?.snapshot)&&value.mtf!==undefined);return fields&&typeof value.reviewId==='string'?{reviewId:value.reviewId,...fields}:null;}catch(_){return null;}}
  const mtfText=m=>m?`\n\nTimeframe relationship: ${m.relationship}\nGoverning context: ${m.governing}\n${m.frames.map(f=>`${f.timeframe}: ${f.reading} ${f.evidence}`).join('\n')}\nSetup condition: ${m.setupCondition}\nSetup invalidated if: ${m.setupInvalidation}\nHigher context changes if: ${m.contextInvalidation}`:'';
  const reviewText=r=>`Market reading: ${r.reading}\n\nSupporting evidence: ${r.support}\n\nMain concern: ${r.concern}\n\nWhat would change this view: ${r.whatChanges}\n\nLimits: ${r.limits}`+mtfText(r.mtf);
  let pendingReview=null,reviewError='',submission=null,connectAttempt=0,pendingReply=null,activeSessionId=null,voiceMode='listening',observedSelection='',continuedSelection='';
  function cancelSubmission(){connectAttempt++;if(submission){const q=submission.question;if(['connecting','sending'].includes(q.delivery)){q.delivery='failed';q.pending=true;}submission=null;}}
  function cancelReview(reason=''){if(pendingReview?.timer)clearTimeout(pendingReview.timer);pendingReview=null;reviewError=reason;}
  function reviewPrompt(id){
    const mtf=isMTF(packet?.snapshot),schema={reviewId:id,reading:'One concise conclusion with its key uncertainty',support:'Observations supporting this reading',concern:'Strongest contrary evidence or uncertainty',whatChanges:'Observable change conditions with the relevant timeframe',limits:'What the supplied data cannot establish'};
    if(mtf)schema.mtf={profile:'intraday-v1',relationship:'aligned | compatible-pullback | conflicting | mixed | undetermined | incomplete',governing:'Which timeframe governs context versus this setup, and why',setupCondition:'A specific completed-candle trigger, its timeframe and observed met/pending status; or no defined trigger',setupInvalidation:'The observable condition that breaks the lower-timeframe setup, with a supplied price and timeframe where justified',contextInvalidation:'A separate observable condition that changes higher-timeframe context; say when available evidence cannot define it',frames:INTRADAY.map(tf=>({timeframe:tf,bias:'bullish | bearish | mixed | undetermined',reading:`Interpret the ${ROLES[tf].toLowerCase()} in one short sentence`,evidence:'Cite supplied swing or price facts; disclose undetermined structure'}))};
    return 'Review the supplied frozen completed-candle evidence independently. Do not use ARIA scores or earlier user ideas to reach your reading. Separate observed facts from interpretation. '+(mtf?'Use the intraday 4h context → 1h active structure → 15m setup → 5m timing hierarchy. Read every supplied frame before concluding. This profile is not universal: the higher frame supplies context, not an automatic veto of a countertrend idea. Do not vote or average across frames. A neutral frame means the direction is only partially aligned; disclose it rather than claiming all frames agree. A lower-frame move against context can be a compatible pullback; explain whether evidence supports that interpretation or genuine conflict. Confirmed 2x2 swings lag by two completed bars and may be undetermined; 20-bar windows have different elapsed durations. Never call a setup confirmed without an explicit observable trigger and whether it occurred. Distinguish setup failure from a change in the broader thesis. If evidence cannot define a trigger/invalidation, say so rather than inventing a price. ':'Address both supplied horizons. ')+'Name contrary evidence. Do not infer news, live screen access, fills or profitability. Missing evidence stays unknown. This is educational analysis, not an entry instruction. Keep reading one concise sentence; other fields at most two short sentences (under 700 characters each). Return ONLY one JSON object, no introduction or markdown, with these exact fields: '+JSON.stringify(schema);
  }

  let doc,adapter,dialog,packet=null,history=[],looseDraft='',busy=false,changingHistory=false,uploading=false,error='',warning='',notice='',seq=0,controller=null,storage,conversation=null,connectedSnapshot=null,returnFocus=null,expandedFrame=null;
  let accountEpoch=0,scopeBlocked=false;
  const storageStatus=fallback=>{try{const value=root.ProTraderStorageStatus?.();return typeof value==='string'&&value?value:fallback;}catch(_){return fallback;}};
  let connection={configured:false,state:'disconnected',mode:'text',reason:'Checking private agent connection…'};
  const uid=()=>root.crypto?.randomUUID?.()||`message-${Date.now()}-${Math.random().toString(36).slice(2,9)}`;
  const draftText=()=>packet?.draft??looseDraft;
  function setDraft(value){if(packet)packet.draft=String(value).slice(0,2000);else looseDraft=String(value).slice(0,2000);}
  function persist(){if(scopeBlocked)return false;try{if(!storage)throw Error();storage.setItem(KEY,JSON.stringify({version:2,active:packet,history,looseDraft}));warning='';return true;}catch(_){warning='This browser could not save the discussion. Keep this tab open and save/export through Journal before closing.';return false;}}
  function clearMessagesBlocked(){
    if(connection.state!=='disconnected')return 'End conversation before clearing messages.';
    if(busy||changingHistory||uploading||submission||pendingReview)return 'Wait for the current operation to finish before clearing messages.';
    return '';
  }
  function confirmRemoval(message){
    if(typeof root.confirm!=='function'){error='Confirmation is unavailable. Nothing was removed.';render();return false;}
    return root.confirm(message+'\n\nThis only removes records from this browser. Saved Journal entries and ElevenLabs conversation records are not deleted.');
  }
  function commitRemoval(nextPacket,nextHistory,message){
    if(scopeBlocked)return false;
    try{if(!storage)throw Error();storage.setItem(KEY,JSON.stringify({version:2,active:nextPacket,history:nextHistory,looseDraft}));}
    catch(_){error='This browser could not save the removal. Your discussion records have been kept. Try again when browser storage is available.';render();return false;}
    packet=nextPacket;history=nextHistory;warning='';error='';notice=message;render();return true;
  }
  function removeHistory(snapshotId){
    if(busy||changingHistory){error='Wait for the evidence update to finish before deleting earlier discussions.';render();return;}
    const selected=snapshotId?history.find(p=>p.snapshot.id===snapshotId):null,oldHistory=history;
    if(snapshotId&&!selected||!history.length)return;
    const description=selected?`Delete the saved ${selected.snapshot.label} · ${selected.analysis.timeframe} discussion, including its review, messages and draft?`:`Clear all ${history.length} earlier discussions, including their reviews, messages and drafts? Your current discussion will be kept.`;
    if(!confirmRemoval(description)||history!==oldHistory||busy||changingHistory)return;
    commitRemoval(packet,selected?history.filter(p=>p!==selected):[],selected?'Saved discussion deleted from this browser. Journal and provider records are unchanged.':'Earlier discussions cleared from this browser. Your current discussion, Journal and provider records are unchanged.');
  }
  function clearMessages(){
    const block=clearMessagesBlocked();if(block){error=block;render();return;}
    const p=packet;if(!p?.questions.length)return;
    if(!confirmRemoval('Clear all messages in this discussion, including questions saved without sending? Your market review, evidence and current draft will be kept.')||packet!==p||clearMessagesBlocked())return;
    if(commitRemoval({...p,questions:[]},history,'Messages cleared from this browser. Your review, evidence, draft, Journal and provider records are unchanged.'))connectedSnapshot=null;
  }
  function normalize(saved){
    if(!saved?.snapshot?.id||!HIGHER[saved?.analysis?.timeframe]||!Array.isArray(saved.questions))return null;
    const questions=saved.questions.filter(q=>q&&typeof q==='object'&&['user','assistant','session'].includes(q.role)&&typeof(q.text??q.question)==='string'&&(q.text??q.question).length<=12000&&q.snapshotId===saved.snapshot.id&&q.dataReference===saved.snapshot.dataReference).slice(-MAX_MESSAGES).map(q=>({...q,id:typeof q.id==='string'?q.id:uid(),text:q.text??q.question,answerState:q.answerState==='waiting'?'interrupted':q.answerState,delivery:['connecting','sending'].includes(q.delivery)?'failed':q.role==='user'?(['saved','sent','failed'].includes(q.delivery)?q.delivery:q.pending?'saved':'sent'):q.delivery}));
    const r=saved.marketReview,fields=reviewFields(r,isMTF(saved.snapshot));const marketReview=fields&&typeof r.reviewId==='string'&&r.reviewId.length>0&&r.reviewId.length<=160&&r.at>0&&Number.isFinite(new Date(r.at).valueOf())&&r.snapshotId===saved.snapshot.id&&r.dataReference===saved.snapshot.dataReference&&Number.isFinite(r.at)?{...fields,reviewId:r.reviewId,snapshotId:r.snapshotId,dataReference:r.dataReference,at:r.at}:null;
    return {...saved,marketReview,analysis:analyze(saved.snapshot,saved.analysis.timeframe),questions,draft:typeof saved.draft==='string'?saved.draft.slice(0,2000):'',connectionCount:Number.isInteger(saved.connectionCount)?saved.connectionCount:0};
  }
  function remember(p){if(!p)return;history=history.filter(old=>old.snapshot.id!==p.snapshot.id);history.unshift(clone(p));history=history.slice(0,MAX_HISTORY);}
  function addMessage(p,message){const q={id:uid(),...message,snapshotId:p.snapshot.id,dataReference:p.snapshot.dataReference,at:Date.now()};p.questions.push(q);if(p.questions.length>MAX_MESSAGES)p.questions.splice(0,p.questions.length-MAX_MESSAGES);return q;}
  const selectionKey=()=>{const c=adapter.getContext();return JSON.stringify([c.symbol,c.timeframe]);};
  function chartMatches(){const c=adapter.getContext();return packet?.snapshot.symbol===c.symbol&&packet?.analysis.timeframe===c.timeframe;}
  function contextMatches(){return !!packet&&(chartMatches()||continuedSelection===packet.snapshot.id+'|'+selectionKey());}
  function settleReply(state){const wait=pendingReply;if(!wait)return;clearTimeout(wait.timer);pendingReply=null;if(wait.question.answerState==='waiting')wait.question.answerState=state;}
  function waitForReply(q,p){
    settleReply('interrupted');q.answerState='waiting';
    const wait={packet:p,question:q,timer:null};pendingReply=wait;
    wait.timer=setTimeout(()=>{if(pendingReply!==wait)return;settleReply('delayed');notice='Oracle has not replied yet. Your question is saved; choose Ask again to reconnect and retry.';connectedSnapshot=null;conversation?.disconnect();persist();render();},90000);wait.timer?.unref?.();
  }
  function discussionContext(){
    if(!packet)return null;
    const p=packet,r=p.marketReview,fields=reviewFields(r,isMTF(p.snapshot));
    const review=fields&&r.snapshotId===p.snapshot.id&&r.dataReference===p.snapshot.dataReference?fields:null;
    return {snapshotId:p.snapshot.id,dataReference:p.snapshot.dataReference,review,messages:p.questions.filter(q=>q.snapshotId===p.snapshot.id&&q.dataReference===p.snapshot.dataReference&&q.purpose!=='market-review'&&(q.role==='user'&&q.delivery==='sent'||q.role==='assistant'&&(!q.interrupted||q.corrected))&&(!review||q.text!==reviewText(review))).map(q=>({role:q.role,text:q.text||q.question,delivery:q.delivery,purpose:q.purpose}))};
  }
  const messageKey=v=>typeof v==='string'||typeof v==='number'?String(v):null;
  function handleMessage(message){
    if(!packet||connectedSnapshot!==packet.snapshot.id||connection.state!=='connected'||!contextMatches())return;
    if(message.role!=='assistant'&&!(message.role==='user'&&connection.mode==='voice'))return;
    if(typeof message.text!=='string'||!message.text.trim())return;
    const p=packet,eventId=messageKey(message.eventId),responseId=messageKey(message.responseId);
    const existing=p.questions.find(q=>q.sessionId===activeSessionId&&q.role===message.role&&(eventId!==null&&q.eventId===eventId||responseId!==null&&q.responseId===responseId));
    if(existing){if(existing.corrected)return;existing.text=message.text;persist();render();return;}
    const parsed=message.role==='assistant'?parseReview(message.text):null;
    let purpose=parsed?'market-review':undefined,reviewCompleted=false;
    if(pendingReview?.packet===p&&pendingReview.state==='waiting'&&message.role==='assistant'){
      if(parsed&&parsed.reviewId===pendingReview.id){
        if(reviewFields(parsed,isMTF(p.snapshot))){p.marketReview={...parsed,snapshotId:p.snapshot.id,dataReference:p.snapshot.dataReference,at:Date.now()};purpose='market-review';reviewCompleted=true;cancelReview();}
        else{purpose='market-review';cancelReview('Oracle returned an incomplete timeframe review. The saved review is unchanged; request another review.');}
      }
    }
    const replyTo=message.role==='assistant'&&!parsed&&pendingReply?.packet===p?pendingReply.question.id:undefined;
    if(message.role==='assistant'){if(!parsed)settleReply('answered');}else settleReply('interrupted');
    const q=addMessage(p,{role:message.role,text:parsed?reviewText(parsed):message.text,question:message.role==='user'?message.text:undefined,delivery:message.role==='user'?'sent':undefined,pending:false,purpose,replyTo,eventId,responseId,sessionId:activeSessionId});
    if(message.role==='user')waitForReply(q,p);
    notice='';persist();render();if(reviewCompleted)showReading();
  }
  function handleInterruption(event={}){
    if(!packet||connectedSnapshot!==packet.snapshot.id||connection.state!=='connected'||connection.mode!=='voice')return;
    const id=messageKey(event.eventId),responses=packet.questions.filter(q=>q.role==='assistant'&&q.sessionId===activeSessionId);
    const q=id!==null?responses.findLast(q=>q.eventId===id||q.responseId===id):(voiceMode==='speaking'?responses.at(-1):null);
    if(id!==null&&!q)return;
    if(q)q.interrupted=true;
    if(q?.replyTo&&q.replyTo===pendingReply?.question.id)settleReply('interrupted');
    voiceMode='listening';persist();render();
  }
  function handleCorrection(event={}){
    if(!packet||connectedSnapshot!==packet.snapshot.id||connection.state!=='connected'||typeof event.correctedText!=='string'||event.correctedText.length>12000)return;
    const id=messageKey(event.eventId),responseId=messageKey(event.responseId);
    const candidates=packet.questions.filter(q=>q.role==='assistant'&&q.sessionId===activeSessionId&&(id!==null?q.eventId===id:responseId!==null?q.responseId===responseId:typeof event.originalText==='string'&&q.text===event.originalText));
    if(candidates.length!==1)return;
    const q=candidates[0];q.text=event.correctedText;q.corrected=true;q.interrupted=true;
    if(q.purpose==='market-review'&&packet.marketReview){notice='The spoken review was interrupted. The saved assessment above remains a separate complete review.';}
    persist();render();
  }
  function age(asOf,now=Date.now()/1000){const seconds=Math.max(0,now-asOf);return seconds<60?'Captured less than a minute ago':seconds<3600?`Captured ${Math.floor(seconds/60)} minutes ago`:seconds<86400?`Captured ${Math.floor(seconds/3600)} hours ago`:`Captured ${Math.floor(seconds/86400)} days ago`;}
  function factsHTML(a){return a.facts.map(f=>`<div class="oa-evidence"><strong>${esc(f.title)}</strong><p>${esc(f.fact)}</p><small>${esc(f.relevance)}</small></div>`).join('');}
  function hierarchyHTML(p,full=false){
    if(!isMTF(p?.snapshot))return '';
    const a=p.analysis,m=p.marketReview?.mtf||a.interpretation,automatic=m===a.interpretation,labels={'aligned':'Aligned','compatible-pullback':'Possible pullback','conflicting':'Conflicting','mixed':'Mixed / partial','undetermined':'Undetermined','incomplete':'Incomplete evidence'};
    const prefix='oaFrame'+(full?'Dialog':'Panel');
    const frameInfo=tf=>{
      const f=a.metrics[tf],r=m?.frames.find(r=>r.timeframe===tf),trend=f?.structure?.trend;
      const bias=r?.bias;
      return {f,r,kind:!f?'unavailable':bias||'observed',label:!f?'Unavailable':automatic&&r?.phase==='Prior structure challenged'?'Challenged':bias?({bullish:'Bullish',bearish:'Bearish',mixed:'Mixed',undetermined:automatic?'No clear trend':'Unclear'}[bias]):trend==='up'?'Up swings':trend==='down'?'Down swings':trend==='mixed'?'Mixed swings':'Unclear swings'};
    };
    return `<section class="oa-hierarchy" aria-label="Multi-timeframe hierarchy"><div class="oa-hierarchy-heading"><h3>How the timeframes fit</h3><span>${m?esc(labels[m.relationship]):'Incomplete evidence'}</span></div>
      <div class="oa-frame-tabs" role="group" aria-label="Timeframe readings">${INTRADAY.map(tf=>{const {label,kind}=frameInfo(tf);return `<button id="${prefix}Chip${tf}" class="oa-frame-chip oa-frame-${kind}" data-oa="frame" data-timeframe="${tf}" aria-expanded="${expandedFrame===tf}" aria-controls="${prefix}${tf}" aria-label="${tf.toUpperCase()} ${ROLES[tf]}: ${label}. ${expandedFrame===tf?'Hide':'Show'} evidence"><strong>${tf.toUpperCase()}</strong><small>${ROLES[tf]}</small><span>${esc(label)}</span></button>`;}).join('')}</div>
      ${m?`<p class="oa-governing">${esc(m.governing)}</p>`:'<p class="oa-method">Completed candles · context → structure → setup → timing. Tap a timeframe for its evidence.</p>'}
      ${INTRADAY.map(tf=>{const {f,r}=frameInfo(tf);return `<div class="oa-frame-detail" id="${prefix}${tf}" data-oa-frame="${tf}" ${expandedFrame===tf?'':'hidden'}><h4>${tf.toUpperCase()} · ${ROLES[tf]}</h4>${r?`<p>${esc(r.reading)}</p>${f?`<p>${esc(r.evidence)}</p>`:''}${automatic?`<p class="oa-frame-change">${esc(r.changeCondition)}</p>`:''}`:''}${f?`<p class="oa-frame-fact">Last close ${fmt(f.close)} · Prior 20-bar range ${fmt(f.low)}–${fmt(f.high)}</p><small>Last completed close · ${esc(cutoff(f.closedAt))}${f.structure?`<br/>Swing window · ${f.structure.lookbackBars} bars · ${esc(cutoff(f.structure.from))} to ${esc(cutoff(f.structure.through))}<br/>Swings require 2 completed bars on either side.`:''}${!r?.bias?'<br/>Chip describes calculated swing structure; it is not an agent direction rating.':''}</small>`:!r?`<p>${esc(a.unknowns.find(u=>u.startsWith(tf+':'))||'No verified completed history for this timeframe. Update evidence to retry.')}</p>`:''}</div>`;}).join('')}</section>`;
  }
  function messageHTML(q,matching,ready){
    if(q.role==='session')return `<p class="oa-session-break">${esc(q.text)}</p>`;
    const labels={saved:'Saved locally · not sent',connecting:'Connecting before sending…',sending:'Sending…',sent:q.answerState==='waiting'?'Waiting for Oracle’s reply…':q.answerState==='delayed'?'Sent · no reply received yet':q.answerState==='interrupted'?'Sent · conversation interrupted':'Sent',failed:'Not sent · retry available'};
    const retry=q.role==='user'&&!q.attachment&&(['saved','failed'].includes(q.delivery)||q.delivery==='sent'&&['delayed','interrupted'].includes(q.answerState));
    return `<article class="oa-message ${q.role==='assistant'?'oa-agent':'oa-user'}"><strong>${q.role==='assistant'?'Oracle':'You'}</strong><p>${esc(q.text??q.question)}</p>${q.role==='assistant'&&q.interrupted?`<small>${q.corrected?'Transcript corrected after interruption.':'Speech interrupted; this text may include words you did not hear.'}</small>`:''}${q.role==='user'?`<small role="status">${labels[q.delivery]||'Saved with this evidence'}</small>${q.answerState==='waiting'?'<button class="oa-link" data-oa="stop-reply">Stop waiting</button>':''}${q.attachment&&(q.delivery==='failed'||['interrupted','delayed'].includes(q.answerState))?'<small>Select the image again to retry; image files are not restored.</small>':''}${retry?`<button class="oa-link" data-oa="retry" data-id="${esc(q.id)}" ${!matching||busy||pendingReview||pendingReply||submission||(!ready&&!connection.configured)?'disabled':''}>${q.delivery==='sent'?'Ask again':!ready?'Connect &amp; send':q.delivery==='saved'?'Send now':'Retry question'}</button>`:''}`:''}</article>`;
  }
  function blockedSend(){
    if(scopeBlocked)return 'Wait for your account data to finish loading.';
    if(!packet)return 'Read current market above to capture evidence before asking Oracle.';
    if(busy)return 'Wait for the market evidence to finish loading. Your draft stays here.';
    if(!contextMatches())return 'Choose Continue this review or Discuss selected chart above before sending.';
    if(uploading)return 'Wait for the chart image to finish uploading before sending another question.';
    if(pendingReply)return 'Waiting for Oracle’s reply. Keep writing, or stop waiting before asking again.';
    if(pendingReview)return 'Oracle is preparing the market review. Wait for it or choose Stop waiting above before asking a question.';
    if(submission)return submission.phase==='connecting'?'Connecting, then sending your question…':'Sending your question…';
    if(connection.state==='connecting')return 'The conversation is connecting. Your draft stays here.';
    if(!conversation||(!connection.configured&&connection.state!=='connected'))return connection.setupMessage||connection.reason||'The private conversation is unavailable. Your draft can still be saved without sending.';
    return '';
  }
  function transcriptHTML(p,matching,ready){
    const local=(p?.questions||[]).filter(q=>q.role==='user'&&['saved','failed'].includes(q.delivery));
    const exchanges=(p?.questions||[]).filter(q=>!local.includes(q)&&q.purpose!=='market-review'),clearBlocked=clearMessagesBlocked();
    return `<section class="oa-transcript" aria-label="Discussion for this snapshot"><div class="oa-messages" data-oa-messages role="log" aria-label="Conversation messages" aria-live="polite" aria-relevant="additions text">${exchanges.length?exchanges.map(q=>messageHTML(q,matching,ready)).join(''):'<p class="oa-chat-note">Ask about the reading, share your idea, or explore what could change the view.</p>'}</div>${local.length?`<details data-oa-section="unsent"><summary>Questions not sent (${local.length})</summary><section aria-label="Questions not sent">${local.map(q=>messageHTML(q,matching,ready)).join('')}</section></details>`:''}${p?.questions.length?`<details data-oa-section="conversation-options"><summary>Conversation options</summary><div class="oa-history-controls"><button class="oa-link" data-oa="clear-messages" ${clearBlocked?'disabled':''}>Clear messages</button>${clearBlocked?`<small>${esc(clearBlocked)}</small>`:'<small>Keeps the review and your draft.</small>'}</div></details>`:''}</section>`;
  }
  function content(full=false){
    const c=adapter.getContext(),p=packet,a=p?.analysis,matching=contextMatches(),ready=connection.state==='connected',connecting=connection.state==='connecting',sending=p?.questions.some(q=>q.delivery==='sending');
    const suffix=full?'Dialog':'Panel';
    const activeMode=ready?(connection.mode==='voice'?(voiceMode==='speaking'?'Oracle is speaking · you can interrupt':'Listening · microphone active'):pendingReply?'Waiting for Oracle’s reply…':'Connected · text'):connecting?(connection.stage==='microphone'?'Waiting for microphone permission…':connection.stage==='audio'?'Preparing audio…':'Connecting…'):'Conversation disconnected';
    const review=p?.marketReview,automatic=a?.interpretation,assessment=review||automatic,assessmentMTF=review?review.mtf:automatic,reviewing=!!pendingReview,m=a?.metrics[a.timeframe],sendBlocked=blockedSend();
    const reviewBlocked=!p||busy||!matching||a?.status!=='Data available'||!connection.configured||connecting||sending||submission||uploading||pendingReply;
    const reviewAction=reviewing?`<p role="status" class="oa-method">${review?'Your saved review stays visible while Oracle prepares another.':'Oracle is preparing a review of the saved evidence.'}</p><button class="oa-link" data-oa="cancel-review">Stop waiting</button>`:`<button class="${review?'oa-secondary':'oa-primary'}" data-oa="review" ${reviewBlocked?'disabled':''}>${review?'Review again':ready&&connection.mode==='text'?'Request market review':ready?'Switch to text &amp; review':'Connect &amp; review'}</button>`;
    const reviewHelp='<p class="oa-method">A review starts a fresh text conversation with this evidence. Earlier messages and your draft stay saved.</p>';
    const mismatch=!chartMatches()&&p?`<div class="oa-chart-choice" role="status"><strong>${matching?'Continuing the saved review':'Choose what to discuss'}</strong><p>This review is ${esc(p.snapshot.label)} · ${esc(a.timeframe)}. The chart is now ${esc(c.label)} · ${esc(c.timeframe)}.</p><div class="oa-actions">${!matching?'<button data-oa="continue-saved">Continue this review</button>':''}<button data-oa="refresh" ${busy||!HIGHER[c.timeframe]?'disabled':''}>Discuss selected chart</button></div><small>${matching?'Questions stay with this saved snapshot until you choose another chart.':'Your earlier discussion and draft will be kept.'}</small></div>`:'';
    const readingTitle=!p?'Read the market before discussing it':a.status!=='Data available'?'Market evidence is incomplete':isMTF(p.snapshot)?'Four-timeframe evidence':m?.close>m?.high?'Close above the prior range':m.close<m.low?'Close below the prior range':'Still inside the prior range';
    const concern=a?.unknowns.find(x=>!x.startsWith('News,'))||a?.alternatives[0]?.fact;
    return `<div class="oa-reader" data-oa-scroll>
      ${!full?'<header class="oa-heading"><div><div class="ow-eyebrow">Oracle</div><p class="oa-subtitle">Independent market review</p></div><button class="oa-link" data-oa="open" aria-label="Expand Oracle review">Expand ↗</button></header>':''}
      <section class="oa-agent-review oa-lead" aria-label="Oracle market review" aria-busy="${reviewing}">
        <p class="oa-context"><strong>${esc(p?.snapshot.label||c.label)} · ${a?esc(horizons(a)):esc(c.timeframe)}</strong></p>
        ${p?`<p class="oa-cutoff" title="Snapshot cutoff · ${esc(cutoff(p.snapshot.asOf))}">${esc(age(p.snapshot.asOf))} · Saved evidence</p>`:''}
        ${assessment?`<p class="oa-read-source">${review?'Connected agent interpretation':'Automatic structure read · completed candles'}</p><h2 class="oa-review-reading">${esc(assessment.reading)}</h2>`:`<h2>${reviewing?'Review in progress…':p&&a.status!=='Data available'?'Evidence is incomplete':'Get Oracle’s view of this market'}</h2><p class="oa-empty-description">${p?'Request a reading grounded in the completed candles.':'Capture completed candles to begin.'}</p>`}
        ${hierarchyHTML(p,full)}
        ${assessment?`<div class="oa-review-section"><h3>Why</h3><p>${esc(assessment.support)}</p></div><div class="oa-review-section oa-watch"><h3>Watch</h3><p>${esc(assessment.concern)}</p>${assessmentMTF?`<p class="oa-setup-condition"><strong>${review?'Setup condition':'15m condition'}</strong> ${esc(assessmentMTF.setupCondition)}</p>`:''}</div><section class="oa-invalidation" aria-label="Invalidation"><h3>${review?'Invalidated if':'What would change this read'}</h3>${assessmentMTF?`<div><h4>${review?'Setup':'15m setup'}</h4><p>${esc(assessmentMTF.setupInvalidation)}</p></div><div><h4>${review?'Higher context':'4H context'}</h4><p>${esc(assessmentMTF.contextInvalidation)}</p></div>`:`<p>${esc(assessment.whatChanges)}</p>`}</section><button class="oa-link oa-discuss-link" data-oa="discuss">Discuss this reading ↓</button>`:reviewAction}
        ${reviewing&&assessment?reviewAction:''}
        ${reviewError?`<p class="oa-error" role="alert">${esc(reviewError)}</p>`:''}
        ${p&&a.status!=='Data available'?`<p class="oa-method">${isMTF(p.snapshot)?'All four completed timeframe histories':'Both completed timeframes'} are needed before requesting a full review. Update evidence to retry.</p>`:''}
        ${!connection.configured&&!reviewing&&!automatic?`<p class="oa-method">${esc(connection.setupMessage||connection.reason||'The private text connection is not configured.')}</p>`:''}
      </section>
      ${mismatch}
      ${!HIGHER[c.timeframe]?`<p class="oa-error">The ${esc(c.timeframe)} chart horizon is not supported. Choose 1m, 5m, 15m, 1h or 4h to capture a new review.</p>`:''}
      <div class="oa-update"><span>${p?'Saved evidence · stays fixed during discussion':'Nothing is sent automatically'}</span><button class="oa-link" data-oa="refresh" ${busy||!HIGHER[c.timeframe]?'disabled':''}>${busy?'Reading histories…':p?'Update evidence':'Read current market'}</button></div>
      <section class="oa-chat" aria-label="Discuss this reading"><h3>Discussion</h3>${transcriptHTML(p,matching,ready)}</section>
      <details class="oa-more" data-oa-section="more"><summary>More options</summary><div class="oa-more-body">
        ${p?`<p class="oa-method">Snapshot cutoff · ${esc(cutoff(p.snapshot.asOf))}. Evidence stays fixed during discussion.</p>`:''}
        <div class="oa-draft-tools"><button class="oa-link" data-oa="keep" ${!p||busy||!matching?'disabled':''}>Save without sending</button><button class="oa-link" data-oa="idea">Start an idea</button></div>
        ${review||automatic?`<details class="oa-review-options" data-oa-section="review-options"><summary>${review?'Request another review':'Request a private agent review'}</summary>${reviewAction}${reviewHelp}${!review?'<p class="oa-method">No agent review has been generated for this snapshot. The automatic structure read above is calculated from candles.</p>':''}${uploading?'<p class="oa-method" role="status">Wait for the chart image to finish uploading before requesting another review.</p>':''}</details>`:`${reviewHelp}<p class="oa-method">No agent review has been generated for this snapshot.</p>`}
        ${assessment?`<details data-oa-section="review-limits"><summary>${review?'Review limits':'Reading method &amp; limits'}</summary><p>${esc(assessment.limits)}</p><small>${review?`Agent interpretation generated ${esc(new Date(review.at).toLocaleString())}. It can be wrong; check the supporting evidence.`:'Automatic structure rules; no agent session is started. Update evidence to calculate a fresh read.'}</small></details>`:''}
        ${p?.questions.some(q=>q.purpose==='market-review')?`<details data-oa-section="review-messages"><summary>Review messages</summary><p class="oa-method">The latest complete assessment leads above. Earlier review requests and replies remain here.</p>${p.questions.filter(q=>q.purpose==='market-review').map(q=>messageHTML(q,matching,ready)).join('')}</details>`:''}
        <details class="oa-market-facts" data-oa-section="market-facts"><summary>Market facts · calculated from candles</summary><section class="oa-reading" aria-label="Calculated market facts"><h3>${readingTitle}</h3>${p?`<p class="oa-summary">${esc(a.summary)}</p><div class="oa-concern"><strong>Main consideration</strong><p>${esc(concern||'Missing evidence prevents a useful comparison.')}</p></div><div class="oa-change"><strong>What would change the calculation?</strong><p>${esc(a.whatChanges[0]?.resolution||'Obtain the missing interval or source, then capture a new snapshot.')}</p></div>`:'<p>Capture completed candles to see the market facts.</p>'}<p class="oa-method">Calculated observations, separate from Oracle’s interpretation.</p></section></details>
        ${p?`<details class="oa-read" data-oa-section="evidence"><summary>Supporting evidence &amp; limits</summary><div class="oa-read-title">${esc(a.status)} · ${esc(p.snapshot.label)} · ${esc(a.timeframe)}</div>${factsHTML(a)}<h3>Alternative reading</h3>${a.alternatives.map(f=>`<p>${esc(f.fact)} ${esc(f.relevance)}</p>`).join('')||'<p>Missing evidence prevents a useful comparison.</p>'}<h3>Evidence limits</h3><ul>${a.unknowns.map(x=>`<li>${esc(x)}</li>`).join('')}</ul><small>${esc(p.snapshot.provider)} · ${esc(p.snapshot.dataReference)}. Forming bars excluded. These calculations are observations, not a calibrated prediction or permission to trade.</small></details>`:''}
        <details class="oa-connection-details" data-oa-section="connection"><summary>Connection &amp; capabilities</summary><p>Text, basic voice startup and image upload have been checked in this preview. Image interpretations can misread candles; compare them with the original chart. Voice activates your microphone only when selected. Chart image explicitly uploads your selected PNG, JPEG or WebP (up to 5 MiB); it is not a live screen feed. Images are not retained in Journal.</p><p>Reconnecting or switching between text and voice carries this saved review and recent sent messages into the new session. Older messages may be omitted. Drafts and unsent questions are excluded. Uploaded image files are not restored; attach the image again if you want Oracle to inspect it.</p><p>${esc(connection.setupMessage||connection.reason||'Checking local connection configuration…')}</p>${ready&&connection.attachments?.available===false?`<p role="status">Chart image: ${esc(connection.attachments.reason||'Image uploads are unavailable for this connection.')}</p>`:''}</details>
        <div class="oa-actions oa-journal"><button data-oa="plan" ${!p||busy?'disabled':''}>Save review &amp; add my plan</button><button class="oa-link" data-oa="journal" ${!p?'disabled':''}>Save review only</button></div>
        ${history.length?`<details class="oa-history" data-oa-section="history"><summary>Earlier discussions (${history.length})</summary>${history.map(old=>`<div><strong>${esc(old.snapshot.label)} · ${esc(old.analysis.timeframe)}</strong><small>Saved through ${esc(when(old.snapshot.asOf))} · ${old.questions.filter(q=>q.role!=='session').length} messages</small><div class="oa-history-controls"><button class="oa-link" data-oa="history" data-id="${esc(old.snapshot.id)}" ${busy||changingHistory?'disabled':''}>Open saved discussion</button><button class="oa-link" data-oa="delete-history" data-id="${esc(old.snapshot.id)}" aria-label="Delete saved ${esc(old.snapshot.label)} ${esc(old.analysis.timeframe)} discussion" ${busy||changingHistory?'disabled':''}>Delete</button></div></div>`).join('')}<button class="oa-link" data-oa="clear-history" ${busy||changingHistory?'disabled':''}>Clear earlier discussions</button><small>Removes local discussions only. Journal saves and provider records stay unchanged.</small></details>`:''}
        <p class="oa-storage" role="status">${esc(warning||storageStatus('Draft and up to 8 earlier discussions (40 messages each) stay in this browser. Save important reviews to Journal; clearing site data removes local records.'))}</p>
      </div></details>
      </div>
      <footer class="oa-compose" aria-label="Ask Oracle"><div class="oa-mode"><strong role="status">${activeMode}</strong>${ready||connecting||submission?`<button class="oa-link" data-oa="disconnect">${connecting?'Cancel connection':'End conversation'}</button>`:''}</div>
        ${error?`<p class="oa-error" role="alert">${esc(error)}</p>`:''}${notice?`<p class="oa-notice" role="status">${esc(notice)}</p>`:''}
        <label for="oaQuestion${suffix}" class="oa-question-label">Your question or idea<textarea id="oaQuestion${suffix}" data-oa-question rows="2" maxlength="2000" enterkeyhint="send" aria-describedby="oaSendHint${suffix} oaSendState${suffix}" placeholder="Challenge this reading or ask about a timeframe…">${esc(draftText())}</textarea></label>
        <div class="oa-composer-tools"><button class="oa-primary" data-oa="ask" ${sendBlocked?'disabled':''}>${submission?(submission.phase==='connecting'?'Connecting…':'Sending…'):ready?'Ask Oracle':'Connect &amp; ask'}</button><button data-oa="connect-voice" ${!p||busy||!matching||!connection.configured||connecting||reviewing||submission||uploading||pendingReply?'disabled':''}>${ready&&connection.mode==='voice'?'Voice connected':'Connect voice'}</button>${ready&&connection.mode==='voice'?`<button data-oa="connect-text" ${submission||uploading||pendingReply?'disabled':''}>Switch to text</button>`:''}<button data-oa="image" title="${esc(!ready?'Connect the conversation to upload a selected chart image':connection.attachments?.reason||'Upload a selected chart image')}" ${!ready||uploading||!matching||reviewing||submission||pendingReply||connection.attachments?.available===false?'disabled':''}>${uploading?'Uploading…':'Chart image'}</button><input hidden type="file" data-oa-image accept="image/png,image/jpeg,image/webp"/></div>
        <p class="oa-compose-hint" id="oaSendHint${suffix}">${ready?'Enter to send':'Enter to connect and send'} · Shift+Enter for a new line.</p>
        <p class="oa-send-state" id="oaSendState${suffix}" role="status" aria-live="polite" ${sendBlocked?'':'hidden'}>${esc(sendBlocked||'Questions use the saved market evidence above.')}</p>
      </footer>`;
  }
  function render({preserveFocus=true}={}){
    const active=doc?.activeElement,focused=preserveFocus&&active?.matches?.('[data-oa-question],[data-oa="frame"]')?{id:active.id,start:active.selectionStart,end:active.selectionEnd}:null;
    const paint=(el,html)=>{if(!el)return;const top=el.scrollTop,readerTop=el.querySelector?.('[data-oa-scroll]')?.scrollTop||0,messages=el.querySelector?.('[data-oa-messages]'),messageScroll=messages?{top:messages.scrollTop,bottom:messages.scrollHeight-messages.clientHeight-messages.scrollTop<64}:null,opened=Array.from(el.querySelectorAll?.('details[data-oa-section][open]')||[]).map(d=>d.dataset.oaSection);el.innerHTML=html;el.scrollTop=top;const nextReader=el.querySelector?.('[data-oa-scroll]');if(nextReader)nextReader.scrollTop=readerTop;const nextMessages=el.querySelector?.('[data-oa-messages]');if(nextMessages)nextMessages.scrollTop=!messageScroll||messageScroll.bottom?nextMessages.scrollHeight:messageScroll.top;for(const key of opened){const item=el.querySelector?.(`[data-oa-section="${key}"]`);if(item)item.open=true;}};
    paint(doc?.getElementById('oracle-panel'),`<div class="oa-panel">${content()}</div>`);
    if(dialog?.open)paint(dialog,`<div class="oa-dialog-head"><strong>Oracle · Independent review</strong><button data-oa="close" aria-label="Close expanded Oracle review">×</button></div><div class="oa-dialog-body">${content(true)}</div>`);
    if(focused){const input=doc.getElementById(focused.id);input?.focus?.({preventScroll:true});if(typeof focused.start==='number')input?.setSelectionRange?.(focused.start,focused.end);}
  }
  function showReading(){for(const surface of [doc?.getElementById('oracle-panel'),dialog?.open?dialog:null]){const reader=surface?.querySelector?.('[data-oa-scroll]');if(reader)reader.scrollTop=0;}}
  async function refresh(){
    if(scopeBlocked)return;
    cancelSubmission();cancelReview();settleReply('interrupted');const n=++seq,c=adapter.getContext(),h={symbol:c.symbol,label:c.label,timeframe:c.timeframe};controller?.abort();connectedSnapshot=null;await conversation?.disconnect();if(n!==seq)return;controller=new AbortController();busy=true;error='';notice='';render();
    let captured=false;
    try{const snapshot=await adapter.captureSnapshot(h,{signal:controller.signal,profile:'intraday-v1'});if(n!==seq||controller.signal.aborted)return;
      if(adapter.getContext().symbol!==h.symbol||adapter.getContext().timeframe!==h.timeframe){error='The chart changed during capture. Update evidence for the selected market.';return;}
      remember(packet);continuedSelection='';packet={id:'oracle-read-'+snapshot.id,version:1,snapshot,analysis:analyze(snapshot,h.timeframe),questions:[],draft:packet?'':looseDraft,connectionCount:0,lessonRef:c.lessonRef||null};looseDraft='';notice=history.length?'New evidence, new discussion. Your earlier discussion and draft are retained below.':'';captured=true;persist();
    }catch(e){if(n===seq&&!controller.signal.aborted)error=e.message||'Market evidence is unavailable. Your previous discussion is retained.';}
    finally{if(n===seq){busy=false;render();if(captured)showReading();}}
  }
  async function selectHistory(snapshotId){const scope=accountEpoch;const selected=history.find(p=>p.snapshot.id===snapshotId);if(!selected||busy||changingHistory)return;changingHistory=true;cancelSubmission();cancelReview();settleReply('interrupted');const n=++seq;controller?.abort();connectedSnapshot=null;render();try{await conversation?.disconnect();if(n!==seq)return;remember(packet);history=history.filter(p=>p.snapshot.id!==snapshotId);packet=clone(selected);continuedSelection='';error='';notice='Viewing a saved discussion under its original evidence. Reconnecting includes its review and recent sent messages.';persist();}finally{if(scope===accountEpoch){changingHistory=false;render({preserveFocus:false});}}}
  async function deliver(q){
    const scope=accountEpoch,p=packet,attempt=connectAttempt,deliveryAttempt=uid();if(!p||!contextMatches()||connection.state!=='connected'||q.snapshotId!==p.snapshot.id||q.delivery==='sending'||pendingReview)return;
    const index=p.questions.indexOf(q);if(index>=0){p.questions.splice(index,1);p.questions.push(q);}
    q.deliveryAttempt=deliveryAttempt;q.delivery='sending';q.pending=false;error='';waitForReply(q,p);persist();render();
    try{await conversation.send(q.text||q.question);if(q.deliveryAttempt!==deliveryAttempt)return;q.delivery='sent';q.pending=false;if(packet===p&&attempt===connectAttempt)notice='';if(packet===p&&attempt===connectAttempt&&draftText().trim()===(q.text||q.question).trim())setDraft('');}
    catch(e){if(q.deliveryAttempt!==deliveryAttempt)return;if(pendingReply?.question===q)settleReply('failed');q.delivery='failed';q.pending=true;if(packet===p&&attempt===connectAttempt)error=e.message||'This question was not sent. Your draft is retained; retry after reconnecting.';}
    finally{if(scope===accountEpoch){if(packet!==p){const old=history.find(item=>item.snapshot.id===p.snapshot.id),saved=old?.questions.find(item=>item.id===q.id);if(saved)Object.assign(saved,q);}persist();render();}}
  }
  async function submitQuestion(q){
    const block=blockedSend();if(block){error=block;render();return;}
    const scope=accountEpoch,p=packet,attempt={packet:p,question:q,sequence:seq,phase:connection.state==='connected'?'sending':'connecting'};submission=attempt;error='';notice='';
    q.delivery=attempt.phase==='connecting'?'connecting':'saved';persist();render();
    try{
      if(connection.state!=='connected')await connect('text');
      if(submission!==attempt||packet!==p||seq!==attempt.sequence||!contextMatches())return;
      if(connection.state!=='connected'||connectedSnapshot!==p.snapshot.id)throw Error(error||'Oracle could not connect. Your question and draft are retained; try again.');
      attempt.phase='sending';q.delivery='saved';await deliver(q);
    }catch(e){if(pendingReply?.question===q)settleReply('failed');q.delivery='failed';q.pending=true;if(packet===p)error=e.message||'The question was not sent. Your draft is retained.';}
    finally{if(scope===accountEpoch){if(submission===attempt)submission=null;persist();render();}}
  }
  async function ask(container,{saveOnly=false}={}){
    const input=container.querySelector('[data-oa-question]'),text=input?.value??draftText(),question=text.trim();
    if(!question){error='Write a question or idea before sending.';render();return;}
    const block=saveOnly?(!packet?'Read current market above before saving a question.':busy?'Wait for evidence to finish loading.':!contextMatches()?'Update evidence for the selected chart before saving.':''):blockedSend();
    if(block){error=block;render();return;}setDraft(text);
    let q=packet.questions.find(q=>q.role==='user'&&q.purpose!=='market-review'&&['saved','failed','connecting','sending'].includes(q.delivery)&&q.text===question);
    if(!q)q=addMessage(packet,{role:'user',question,text:question,pending:true,delivery:'saved'});
    persist();if(saveOnly){notice=['connecting','sending'].includes(q.delivery)?'This question is already being sent. It remains saved with this discussion.':'Question saved here only. Choose Send now on it when you want an answer.';error='';render();}else await submitQuestion(q);
  }
  async function uploadImage(input){const file=input.files?.[0];if(!file||!packet||!conversation||uploading||!contextMatches()||pendingReview||pendingReply||submission)return;const scope=accountEpoch,p=packet,packetId=p.snapshot.id,attempt=connectAttempt;const container=input.closest('.oa-dialog-body,.oa-panel');const text=container.querySelector('[data-oa-question]')?.value.trim()||draftText().trim();
    const q=addMessage(p,{role:'user',question:text,text:`Chart image: ${file.name}${text?' — '+text:''}. Image file is not retained in Journal.`,pending:false,delivery:'sending',attachment:{name:file.name,type:file.type,size:file.size,retained:false}});
    uploading=true;error='';waitForReply(q,p);persist();render();
    try{const sent=await conversation.sendAttachment(file,{text});if(sent.snapshotId!==packetId)throw Error('The image response belongs to different evidence. Choose your image again.');q.delivery='sent';if(packet===p&&attempt===connectAttempt&&draftText().trim()===text)setDraft('');}
    catch(e){if(pendingReply?.question===q)settleReply('failed');q.delivery='failed';q.pending=true;if(packet===p&&attempt===connectAttempt)error=(e.message||'The chart image was not sent.')+' Choose the image again to retry; your question is retained.';}
    finally{if(scope===accountEpoch){if(packet!==p){const saved=history.find(item=>item.snapshot.id===p.snapshot.id)?.questions.find(item=>item.id===q.id);if(saved)Object.assign(saved,q);}uploading=false;persist();render();}}
  }
  async function connect(mode,{purpose='discussion'}={}){if(!packet||!conversation||!contextMatches()||busy||uploading||pendingReply)return;error='';const attempt=++connectAttempt,p=packet,already=connection.state==='connected'&&connection.mode===mode;connectedSnapshot=p.snapshot.id;
    try{await conversation.connect({mode,purpose});if(attempt!==connectAttempt||packet!==p||connectedSnapshot!==p.snapshot.id||connection.state!=='connected')return;if(!already){p.connectionCount=(p.connectionCount||0)+1;addMessage(p,{role:'session',text:purpose==='review'?'Fresh independent market review.':`Continuing in ${mode}. The saved review and recent sent messages are included.`});persist();}render();}
    catch(e){if(attempt!==connectAttempt)return;if(packet===p)error=e.message||'The private agent could not connect. Your draft is retained.';render();}
  }
  async function requestReview(){
    if(!packet||!conversation||busy||uploading||pendingReview||pendingReply||submission||!contextMatches()||packet.analysis.status!=='Data available'||!connection.configured||packet.questions.some(q=>q.delivery==='sending'))return;
    const scope=accountEpoch,p=packet,r={packet:p,id:uid(),state:'connecting',timer:null};pendingReview=r;reviewError='';render();
    try{
      connectedSnapshot=null;await conversation.disconnect();
      if(pendingReview!==r||packet!==p||!contextMatches())return;
      await connect('text',{purpose:'review'});
      if(pendingReview!==r||packet!==p||!contextMatches())return;
      if(connection.state!=='connected'||connection.mode!=='text')throw Error('Oracle could not connect. The saved review and your draft are unchanged.');
      r.state='waiting';
      const q=addMessage(p,{role:'user',text:isMTF(p.snapshot)?'Review the 4H, 1H, 15m and 5m hierarchy: conclusion, evidence, conflicts and separate setup/context invalidation.':'Review this saved market: the reading, supporting evidence, main concern, what would change it, and limits.',delivery:'sending',purpose:'market-review',reviewRequestId:r.id});
      r.timer=setTimeout(()=>{if(pendingReview===r){cancelReview('No complete review arrived. Your discussion is saved; request another review when ready.');persist();render();}},90000);r.timer?.unref?.();
      persist();render();
      try{await conversation.send(reviewPrompt(r.id),{purpose:'review'});q.delivery='sent';}catch(e){q.delivery='failed';throw e;}
    }catch(e){if(pendingReview===r)cancelReview(e.message||'The review could not be requested. Your draft is retained.');}
    finally{if(scope===accountEpoch){persist();render();}}
  }
  function initializeConversation(){
    const epoch=accountEpoch,live=fn=>(...args)=>{if(epoch===accountEpoch&&!scopeBlocked)return fn(...args);};
    const current=()=>{if(epoch!==accountEpoch||scopeBlocked)throw Error('The account changed. Start a new conversation.');};
    if(!root.OracleConversation){connection.reason='Conversation connection module is unavailable.';return;}
    conversation=root.OracleConversation.create({getEvidence:()=>{current();return root.OracleEvidence?.extract(packet?.snapshot,packet?.analysis.timeframe)||{available:false,unknowns:['No validated evidence extractor is available.']};},getDiscussionContext:()=>{current();return discussionContext();},
      onStatus:live(status=>{
        const previous=connection.state,hadPending=!!pendingReply||!!submission;connection={...connection,...status,reason:status.reason||status.message||''};
        if(status.state==='connecting'&&previous!=='connecting'){activeSessionId=uid();voiceMode='listening';}
        if(status.state==='disconnected'){activeSessionId=null;voiceMode='listening';settleReply('interrupted');if(submission&&previous!=='disconnected'){cancelSubmission();error='The connection ended before this question was sent. Your draft is retained; try again.';}}
        if(status.state==='disconnected'&&pendingReview?.state==='waiting')cancelReview('The connection ended before a complete review arrived. Reconnect to request another.');if(status.state==='disconnected'&&hadPending)persist();render();
      }),onMessage:live(handleMessage),
      onModeChange:live(event=>{if(connection.state!=='connected'||connection.mode!=='voice'||!['speaking','listening'].includes(event.mode))return;voiceMode=event.mode;render();}),
      onInterruption:live(handleInterruption),onResponseCorrection:live(handleCorrection),
      onError:live(message=>{if(pendingReview?.state==='waiting')cancelReview('The review was interrupted. Your saved review and discussion are retained.');const waiting=!!pendingReply;settleReply('interrupted');error=typeof message==='string'?message:message?.message||'Conversation failed.';if(waiting){connectedSnapshot=null;conversation?.disconnect();persist();}render();})});
    conversation.status().then(live(status=>{connection={...connection,...status,reason:status.reason||status.message||'',setupMessage:status.message||status.reason||''};render();})).catch(live(()=>{connection.reason='Private-agent connection status is unavailable.';render();}));
  }
  function open(){returnFocus=doc.activeElement;if(!dialog.open)dialog.showModal();render({preserveFocus:false});dialog.scrollTop=0;dialog.querySelector?.('[data-oa="close"]')?.focus?.({preventScroll:true});if(!packet&&!busy)refresh();}
  function transcriptRevision(questions){let hash=2166136261;for(const c of JSON.stringify(questions.map(q=>[q.id,q.text,q.delivery,q.answerState,q.interrupted,q.corrected])))hash=Math.imul(hash^c.charCodeAt(0),16777619);return (hash>>>0).toString(16);}
  function journal(plan){if(!packet)return;try{const saved=adapter.saveToJournal(clone({...packet,id:packet.id+'-r'+(packet.marketReview?.reviewId||'facts')+'-m'+(packet.questions.at(-1)?.id||'none')+'-t'+transcriptRevision(packet.questions)}));dialog.close();adapter.openJournal(plan?{originReviewId:saved.id}:{savedAnalysisId:saved.id});}catch(e){error=e.message||'The review could not be saved. Your discussion remains here.';render();}}
  function readStorage(){
    try{storage=root.localStorage;const raw=storage?.getItem(KEY);if(raw){const saved=JSON.parse(raw);packet=normalize(saved.version===2?saved.active:saved);history=(saved.version===2&&Array.isArray(saved.history)?saved.history:[]).map(normalize).filter(Boolean).filter(p=>p.snapshot.id!==packet?.snapshot.id).slice(0,MAX_HISTORY);looseDraft=typeof saved.looseDraft==='string'?saved.looseDraft.slice(0,2000):'';if(!packet&&!history.length)warning='Saved discussion is unreadable; it has been left untouched.';}}catch(_){warning='Preview storage is unavailable. Save/export through Journal before closing.';}
  }
  function clearForAccountChange(){
    // Invalidate callbacks before disconnect: old-account events must not persist into the next scope.
    accountEpoch++;scopeBlocked=true;seq++;controller?.abort();controller=null;
    cancelSubmission();cancelReview();settleReply('interrupted');
    const previous=conversation;conversation=null;storage=null;
    packet=null;history=[];looseDraft='';busy=false;changingHistory=false;uploading=false;expandedFrame=null;
    error='';warning='';notice='';connectedSnapshot=null;activeSessionId=null;voiceMode='listening';continuedSelection='';
    connection={configured:false,state:'disconnected',mode:'text',reason:'Loading account data…'};
    dialog?.close();if(doc)render({preserveFocus:false});
    if(previous)Promise.resolve().then(()=>previous.disconnect()).catch(()=>{});
  }
  function reloadStorage(){
    if(!doc){scopeBlocked=false;return;}
    clearForAccountChange();scopeBlocked=false;observedSelection=selectionKey();readStorage();initializeConversation();render({preserveFocus:false});
  }
  function mount(documentRef,adapterRef){if(doc){adapter=adapterRef;render();return;}doc=documentRef;adapter=adapterRef;observedSelection=selectionKey();
    readStorage();
    dialog=doc.createElement('dialog');dialog.className='oa-dialog';dialog.id='oracleAnalystDialog';dialog.setAttribute('aria-label','Expanded Oracle market review');doc.body.appendChild(dialog);
    const handle=e=>{const button=e.target.closest('[data-oa]');if(!button||button.disabled)return;const a=button.dataset.oa,container=button.closest('.oa-dialog-body,.oa-panel')||dialog;
      if(a==='open')open();else if(a==='close'){dialog.close();returnFocus?.focus?.({preventScroll:true});}else if(a==='refresh')refresh();else if(a==='ask')ask(container);else if(a==='keep')ask(container,{saveOnly:true});
      else if(a==='continue-saved'){if(!packet||busy)return;continuedSelection=packet.snapshot.id+'|'+selectionKey();error='';render();}
      else if(a==='frame'&&INTRADAY.includes(button.dataset.timeframe)){expandedFrame=expandedFrame===button.dataset.timeframe?null:button.dataset.timeframe;render();}
      else if(a==='stop-reply'){settleReply('interrupted');connectedSnapshot=null;conversation?.disconnect();notice='Stopped waiting. Your question is saved; choose Ask again when ready.';persist();render();}
      else if(a==='discuss'){const field=container.querySelector('[data-oa-question]');field?.focus?.({preventScroll:true});field?.scrollIntoView?.({block:'center',behavior:'auto'});}
      else if(a==='idea'){const input=container.querySelector('[data-oa-question]');if(!input.value.trim()){input.value='My idea is: ';setDraft(input.value);persist();}notice='Describe what you see, what you expect and what would change your mind. Then choose Ask Oracle.';render();const field=doc.getElementById(input.id)||container.querySelector('[data-oa-question]');field?.focus({preventScroll:true});field?.setSelectionRange(field.value.length,field.value.length);}
      else if(a==='image')container.querySelector('[data-oa-image]')?.click();else if(a==='plan')journal(true);else if(a==='journal')journal(false);
      else if(a==='review')requestReview();else if(a==='cancel-review'){cancelReview('Stopped waiting. Any later reply stays in the discussion and will not replace your saved review.');persist();render();}
      else if(a==='retry'){const q=packet?.questions.find(q=>q.id===button.dataset.id);if(q?.purpose==='market-review')requestReview();else if(q)submitQuestion(q);}
      else if(a==='history')selectHistory(button.dataset.id);else if(a==='delete-history')removeHistory(button.dataset.id);else if(a==='clear-history')removeHistory();else if(a==='clear-messages')clearMessages();else if(a==='connect-text'&&!submission)connect('text');else if(a==='connect-voice'&&!submission)connect('voice');else if(a==='disconnect'){cancelSubmission();cancelReview();settleReply('interrupted');connectedSnapshot=null;conversation?.disconnect();}
    };
    const imageChange=e=>{if(e.target.matches('[data-oa-image]'))uploadImage(e.target);};
    const input=e=>{if(e.target.matches('[data-oa-question]')){setDraft(e.target.value);persist();}};
    const keydown=e=>{if(!e.target.matches?.('[data-oa-question]'))return;e.stopPropagation();if(e.key!=='Enter'||e.shiftKey||e.isComposing||e.keyCode===229)return;e.preventDefault();if(e.repeat)return;const container=e.target.closest('.oa-dialog-body,.oa-panel');if(container)ask(container);};
    dialog.addEventListener('keydown',e=>{keydown(e);e.stopPropagation();});dialog.addEventListener('click',handle);dialog.addEventListener('change',imageChange);dialog.addEventListener('input',input);
    const panel=doc.getElementById('oracle-panel');panel?.addEventListener('click',handle);panel?.addEventListener('change',imageChange);panel?.addEventListener('input',input);panel?.addEventListener('keydown',keydown);initializeConversation();render();
  }
  function contextChanged(){const key=selectionKey();if(key===observedSelection)return;observedSelection=key;continuedSelection='';cancelSubmission();cancelReview();settleReply('interrupted');seq++;controller?.abort();busy=false;connectedSnapshot=null;conversation?.disconnect();render();}
  return{mount,render,open,refresh,analyze,contextChanged,clearForAccountChange,reloadStorage,storageKey:KEY,getPacket:()=>packet?clone(packet):null,getHistory:()=>clone(history)};
});
