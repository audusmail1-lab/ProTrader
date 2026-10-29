/* Evidence capture and delayed ARIA comparison. This module submits no orders. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.OracleMarket=api;})(globalThis,function(){
  'use strict';
  const HIGHER=Object.freeze({'1m':'15m','5m':'1h','15m':'1h','1h':'4h','4h':'1d'});
  const SECONDS=Object.freeze({'1m':60,'5m':300,'15m':900,'1h':3600,'4h':14400,'1d':86400});
  const INTRADAY_TIMEFRAMES=Object.freeze(['4h','1h','15m','5m']);
  const copy=v=>JSON.parse(JSON.stringify(v));
  function freeze(v){if(v&&typeof v==='object'){Object.values(v).forEach(freeze);Object.freeze(v);}return v;}
  function reference(v){
    const text=JSON.stringify(v);let h=2166136261;
    for(let i=0;i<text.length;i++){h^=text.charCodeAt(i);h=Math.imul(h,16777619);}
    return 'fnv1a32-'+(h>>>0).toString(16).padStart(8,'0');
  }
  function intervalError(candles,tf,{requireObservedInterval=false}={}){
    if(!Array.isArray(candles)||!candles.length)return 'No candle history returned.';
    let observedInterval=false;
    for(let i=0;i<candles.length;i++){
      const c=candles[i];
      if(!c||!['time','open','high','low','close'].every(k=>typeof c[k]==='number'&&Number.isFinite(c[k]))||
        !Number.isInteger(c.time)||c.time<=0||c.low<=0||c.high<Math.max(c.open,c.close,c.low)||c.low>Math.min(c.open,c.close))return 'Invalid OHLC or timestamp in supplied history.';
      if(i){
        const gap=c.time-candles[i-1].time;
        if(gap<SECONDS[tf]||(requireObservedInterval&&gap%SECONDS[tf]!==0))return 'Supplied candle intervals do not match '+tf+'.';
        if(gap===SECONDS[tf])observedInterval=true;
      }
    }
    if(requireObservedInterval&&!observedInterval)return 'No consecutive candles establish the requested '+tf+' interval.';
    return '';
  }
  function compare(review,h,s,aria){
    const result={factsAgreed:[],interpretationsDiffer:[],missing:[],notes:[]};
    if(!aria||!aria.available){result.missing.push(aria?.reason||'ARIA has no comparable frozen candidate for this snapshot.');return freeze(result);}
    if(aria.snapshotId!==s.id||aria.symbol!==s.symbol||aria.timeframe!==h.timeframe){
      result.missing.push('The ARIA candidate has a different instrument, horizon or evidence snapshot. It cannot be treated as agreement or disagreement.');return freeze(result);
    }
    result.factsAgreed.push(`Both records use ${s.label||s.symbol}, ${h.timeframe} closed candles through ${new Date(aria.closedAt*1000).toISOString()}; last close ${aria.lastClose}.`);
    result.notes.push('These price facts come from the same saved data. They are shared evidence, not two independent data sources.');
    result.notes.push(`ARIA applies its existing momentum/checklist candidate method on ${h.timeframe}. Oracle reviews your declared ${h.method} method, higher-timeframe context, internal logic, paper risk and evidence quality. A difference in method is not proof that either forecast is right.`);
    if(h.action==='wait')result.interpretationsDiffer.push(`You chose a deliberate wait. ARIA has a ${aria.direction} candidate (${aria.verdict}); a candidate does not supply your missing trigger or require an entry.`);
    else if(h.action!==aria.direction)result.interpretationsDiffer.push(`Your ${h.action} hypothesis differs from ARIA's ${aria.direction} candidate (${aria.verdict}). Review the declared method and the saved ${HIGHER[h.timeframe]} context; an intentional reversal idea can differ from a momentum candidate.`);
    else result.notes.push(`ARIA's candidate points ${aria.direction}, the same direction as your hypothesis. This directional agreement adds no calibrated win probability and does not remove Oracle's concerns or unknowns.`);
    result.notes.push(`Oracle's first assessment remains “${review.assessment}”. It was computed before ARIA's score, verdict or explanation was supplied.`);
    result.missing.push('ARIA does not assess your own cost, exposure or invalidation explanation; the candidate is not a second check of those inputs.');
    for(const f of review.unknowns||[])if(f.essential)result.missing.push(f.title+': '+f.fact);
    for(const limitation of aria.limitations||[])result.notes.push(limitation);
    result.notes.push('This comparison is frozen. The live ARIA panel can differ because its current candle, session or data has changed.');
    return freeze(result);
  }
  function createService({getContext,loadRow,captureExecution,captureAria,lessonRef=()=>null,now=Date.now,id=()=>crypto.randomUUID()}){
    async function captureSnapshot(h,{signal,profile}={}){
      if(!HIGHER[h.timeframe])throw Error('Choose a supported horizon: 1m, 5m, 15m, 1h or 4h.');
      if(profile!==undefined&&profile!=='intraday-v1')throw Error('Choose a supported Oracle evidence profile.');
      const intraday=profile==='intraday-v1';
      if(signal?.aborted)throw Error('Evidence capture cancelled.');
      const asOf=now()/1000,context=getContext(h.symbol);
      if(context.symbol!==h.symbol)throw Error('The selected instrument is unavailable.');
      const rawExecution=captureExecution(h.symbol,asOf);
      // JSON transport cannot represent NaN/Infinity. Preserve an explicit
      // invalid-source marker so a student declaration cannot replace it.
      if(rawExecution.account){
        const invalid=['perIdeaLimit','combinedLimit','dailyLossLimit'].filter(k=>rawExecution.account[k]!=null&&
          (typeof rawExecution.account[k]!=='number'||!Number.isFinite(rawExecution.account[k])||rawExecution.account[k]<0));
        rawExecution.account.invalidLimits=[...new Set([...(rawExecution.account.invalidLimits||[]),...invalid])];
      }
      const execution=copy(rawExecution);
      const snapshot={version:1,id:id(),asOf,capturedAt:asOf,symbol:h.symbol,label:context.label,
        provider:context.provider,series:{},...execution,lessonRef:copy(lessonRef()),
        unsupported:['news','macro events','order flow','hidden liquidity','validated edge']};
      if(intraday)snapshot.profile=profile;
      for(const tf of intraday?INTRADAY_TIMEFRAMES:[h.timeframe,HIGHER[h.timeframe]]){
        if(signal?.aborted)throw Error('Evidence capture cancelled.');
        try{
          const candles=await loadRow(context,tf,signal);
          if(signal?.aborted)throw Error('Evidence capture cancelled.');
          const error=intervalError(candles,tf,{requireObservedInterval:intraday});
          snapshot.series[tf]={status:error?'unavailable':'ready',candles:copy(candles),source:context.provider,capturedAt:now()/1000,...(error?{error}:{})};
        }catch(e){
          if(signal?.aborted)throw Error('Evidence capture cancelled.');
          snapshot.series[tf]={status:'unavailable',candles:[],source:context.provider,capturedAt:now()/1000,error:e.message||'History unavailable'};
        }
      }
      snapshot.capturedAt=now()/1000;
      snapshot.dataReference=reference(snapshot);
      return freeze(snapshot);
    }
    return {getContext:()=>freeze(copy(getContext())),captureSnapshot,
      captureAria:(s,h)=>freeze(copy(captureAria(s,h))),compare};
  }
  return {HIGHER,SECONDS,INTRADAY_TIMEFRAMES,freeze,reference,intervalError,compare,createService};
});
