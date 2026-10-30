/* Sanitized market context for Oracle's conversational runtime.
 * Derives observations from validated completed OHLC only. It never copies a
 * stored analysis, user thesis, ARIA endorsement, account or execution fields.
 * Availability is relative to the saved cutoff, never to a later wall clock.
 */
(function(root,factory){
  const api=factory();
  if(typeof module==='object'&&module.exports)module.exports=api;
  else root.OracleEvidence=api;
})(typeof globalThis==='object'?globalThis:this,function(){
  'use strict';
  const VERSION=1,MINIMUM_BARS=30,MAXIMUM_BARS=5000;
  const SECONDS=Object.freeze({'1m':60,'5m':300,'15m':900,'1h':3600,'4h':14400,'1d':86400});
  const HIGHER=Object.freeze({'1m':'15m','5m':'1h','15m':'1h','1h':'4h','4h':'1d'});
  const INTRADAY_TIMEFRAMES=Object.freeze(['4h','1h','15m','5m']);
  const SWING_LOOKBACK=120,CONFIRMATION_BARS=2;
  const SOURCES=Object.freeze({Deriv:'Deriv',Yahoo:'Yahoo Finance'});
  const finite=n=>typeof n==='number'&&Number.isFinite(n);
  const positive=n=>finite(n)&&n>0;
  const identifier=v=>typeof v==='string'&&/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(v)?v:null;
  const symbol=v=>typeof v==='string'&&/^[A-Za-z0-9^][A-Za-z0-9_.^:/=-]{0,47}$/.test(v)?v:null;
  function freeze(v){if(v&&typeof v==='object'){Object.values(v).forEach(freeze);Object.freeze(v);}return v;}
  function trustedSource(value,provider,tf){
    // The capture service writes known provider names. Accept its controlled
    // interval descriptor as well, but construct the exported label ourselves:
    // upstream/source text must never become model instructions or user prose.
    return value===provider || value===`${provider} · independently requested ${tf} history`;
  }
  function confirmedStructure(closed,seconds){
    // Only completed bars enter this bounded window. A pivot is first knowable
    // when its second right-hand candle closes; neither forming bars nor later
    // wall time can supply that confirmation to a saved snapshot.
    const window=closed.slice(-SWING_LOOKBACK),swingHighs=[],swingLows=[];
    for(let i=CONFIRMATION_BARS;i<window.length-CONFIRMATION_BARS;i++){
      const candidate=window[i],neighbors=[window[i-2],window[i-1],window[i+1],window[i+2]];
      const confirmedAt=window[i+CONFIRMATION_BARS].time+seconds;
      if(neighbors.every(bar=>candidate.high>bar.high))swingHighs.push({time:candidate.time,price:candidate.high,confirmedAt});
      if(neighbors.every(bar=>candidate.low<bar.low))swingLows.push({time:candidate.time,price:candidate.low,confirmedAt});
    }
    const highs=swingHighs.slice(-2),lows=swingLows.slice(-2),last=window.at(-1);
    let trend='undetermined';
    if(highs.length===2&&lows.length===2){
      const highChange=highs[1].price-highs[0].price,lowChange=lows[1].price-lows[0].price;
      trend=highChange>0&&lowChange>0?'up':highChange<0&&lowChange<0?'down':'mixed';
    }
    const relation=pivot=>!pivot?'unknown':last.close>pivot.price?'above':last.close<pivot.price?'below':'at';
    return {method:'confirmed-swings-2x2-v1',confirmationBars:CONFIRMATION_BARS,maximumLookbackBars:SWING_LOOKBACK,
      lookbackBars:window.length,from:window[0].time,through:last.time+seconds,
      swingHighs:highs,swingLows:lows,trend,lastCloseVsHigh:relation(highs.at(-1)),lastCloseVsLow:relation(lows.at(-1))};
  }
  function extract(snapshot,timeframe){
    const s=snapshot&&typeof snapshot==='object'?snapshot:{};
    const intraday=s.profile==='intraday-v1';
    const tf=Object.hasOwn(HIGHER,timeframe)?timeframe:null,higher=!intraday&&tf?HIGHER[tf]:null;
    const out={version:intraday?2:VERSION,available:false,snapshotId:identifier(s.id),symbol:symbol(s.symbol),
      timeframe:tf,higherTimeframe:higher,asOf:positive(s.asOf)?s.asOf:null,
      capturedAt:positive(s.capturedAt)?s.capturedAt:null,dataReference:identifier(s.dataReference),
      frames:{},facts:[],unknowns:[],scope:'Completed-candle market observations only; no execution signal or probability estimate.',
      notAssessed:['news','macro events','order flow','hidden liquidity','institutional intent','execution signals','broker fills and costs','account exposure','validated trading edge'],
      limitations:[
        'Source identity is taken from the capture service metadata; this extractor does not authenticate a provider or establish predictive validity.',
        'Prior price bounds and close displacement describe a saved sample, not hidden orders, a universal trading rule or future direction.',
        'The historical cutoff is pinned. A new capture is required for new evidence; later wall time cannot complete a saved forming bar.'
      ]};
    if(intraday){
      out.profile='intraday-v1';out.requiredTimeframes=[...INTRADAY_TIMEFRAMES];
      out.limitations.push('Intraday structure uses strict two-left/two-right confirmed swing pivots within at most 120 completed candles per interval. A pivot is unavailable until the second right-hand candle closes; equal highs or lows are not pivots.');
      out.limitations.push('Swing structure describes this bounded sample. A higher timeframe supplies context, not an automatic veto or a guarantee; disagreement between intervals is retained.');
    }
    const unknown=(code,interval,message)=>out.unknowns.push({code,timeframe:interval,message,essential:true});
    if(s.profile!==undefined&&!intraday)unknown('unsupported-profile',null,'The saved evidence profile is unsupported.');
    if(!tf)unknown('unsupported-timeframe',null,intraday?'A supported chart interval is required to identify this intraday review.':'A supported primary interval and mapped higher interval are required.');
    if(!out.snapshotId||!out.symbol)unknown('snapshot-identity',null,'A valid snapshot identifier and instrument identifier are required.');
    if(!out.asOf||!out.capturedAt||out.asOf>out.capturedAt)unknown('snapshot-cutoff',null,'The saved decision cutoff and capture time are missing or inconsistent.');
    const provider=Object.hasOwn(SOURCES,s.provider)?s.provider:null;
    if(!provider)unknown('source-provider',null,'The snapshot does not identify a supported candle provider.');
    if(out.unknowns.length)return freeze(out);

    function frame(interval){
      const row=s.series&&typeof s.series==='object'?s.series[interval]:null,seconds=SECONDS[interval];
      const fail=(code,message)=>{unknown(code,interval,message);return null;};
      if(!row||row.status!=='ready'||!Array.isArray(row.candles))return fail('history-unavailable','The required interval history is unavailable; upstream error prose is not included.');
      if(!trustedSource(row.source,provider,interval))return fail('history-source','The interval has no matching identified capture-service source.');
      if(!positive(row.capturedAt)||row.capturedAt<out.asOf||row.capturedAt>out.capturedAt)
        return fail('history-cutoff','The interval capture timestamp cannot support the saved cutoff.');
      const supplied=row.candles;
      if(supplied.length>MAXIMUM_BARS)return fail('history-bound','The supplied history exceeds the bounded evidence window.');
      let previous=null;
      const closed=[];
      for(const b of supplied){
        if(!b||!['time','open','high','low','close'].every(k=>finite(b[k]))||!Number.isInteger(b.time)||b.time<=0||
          b.low<=0||b.high<Math.max(b.open,b.close,b.low)||b.low>Math.min(b.open,b.close))
          return fail('history-integrity','The supplied OHLC values or timestamps are invalid.');
        if(previous!==null){const gap=b.time-previous;
          if(gap<seconds||gap%seconds!==0)return fail('interval-integrity','The history has duplicate, unordered or incompatible interval spacing.');
        }
        previous=b.time;
        if(b.time+seconds<=out.asOf)closed.push(b);
      }
      if(closed.length<MINIMUM_BARS)return fail('history-insufficient','At least 30 completed candles are required for this interval.');
      // Integer-multiple gaps alone could accept hourly candles relabelled as
      // 5m. Require one observed native interval among completed candles while
      // still allowing aligned gaps across market sessions.
      if(intraday&&!closed.some((bar,i)=>i>0&&bar.time-closed[i-1].time===seconds))
        return fail('interval-integrity','No consecutive completed candles establish the requested interval.');
      const last=closed.at(-1),closedAt=last.time+seconds;
      if(out.asOf-closedAt>Math.max(180,seconds*2))return fail('history-stale','The last completed candle is stale at the saved cutoff or the market is closed.');
      const prior=closed.slice(-21,-1),window=closed.slice(-20);
      const prior20Low=Math.min(...prior.map(b=>b.low)),prior20High=Math.max(...prior.map(b=>b.high));
      const closeDisplacement20=last.close-window[0].close;
      // Divide each nonnegative term before summing to avoid overflowing an
      // otherwise finite mean when each input remains a finite OHLC number.
      const meanRange20=window.reduce((sum,b)=>sum+(b.high-b.low)/20,0);
      if(![prior20Low,prior20High,closeDisplacement20,meanRange20].every(finite))
        return fail('derived-integrity','The supplied prices cannot produce finite bounded market facts.');
      const source=`${SOURCES[provider]} · ${interval} candle history`;
      const refs=[`${out.snapshotId}:${interval}:${last.time}`,`${out.snapshotId}:${interval}:${prior[0].time}`];
      const facts={timeframe:interval,source,closedAt,closedBars:closed.length,lastClose:last.close,
        prior20Low,prior20High,closeDisplacement20,meanRange20,
        lastClosePosition:last.close>prior20High?'above':last.close<prior20Low?'below':
          last.close===prior20High||last.close===prior20Low?'at-boundary':'inside',
        structureFrom:prior[0].time,structureThrough:prior.at(-1).time+seconds,
        displacementFrom:window[0].time+seconds,refs};
      if(intraday)facts.structure=confirmedStructure(closed,seconds);
      out.frames[interval]=facts;
      out.facts.push({id:`closed-structure-${interval}`,...facts});
      return facts;
    }
    if(intraday){
      const frames=INTRADAY_TIMEFRAMES.map(frame);
      out.available=frames.every(Boolean);
    }else{
      const primary=frame(tf),higherContext=frame(higher);
      out.available=!!primary&&!!higherContext;
    }
    return freeze(out);
  }
  // A reproducible interpretation of the validated, frozen evidence. This is
  // deliberately separate from an authenticated conversational agent review.
  // Hierarchy follows timeframe roles; direction is never a majority vote.
  function interpret(evidence){
    const e=evidence?.profile==='intraday-v1'?evidence:null;
    const roles={'4h':'Context','1h':'Active structure','15m':'Setup','5m':'Timing'};
    const price=n=>n.toLocaleString('en-US',{maximumSignificantDigits:10});
    const direction=bias=>bias==='bullish'?'bullish':bias==='bearish'?'bearish':null;
    const frame=tf=>{
      const f=e?.frames?.[tf],s=f?.structure,role=roles[tf],name=tf.toUpperCase();
      if(!f||!s){
        const reason=e?.unknowns?.find(u=>u.timeframe===tf)?.message||'No validated completed-candle history is available for this timeframe.';
        return {timeframe:tf,role,bias:'unavailable',verdict:'Unavailable',phase:'Missing evidence',reading:`${name}: ${reason}`,evidence:reason,changeCondition:`Capture valid, recent ${name} history before assessing this ${role.toLowerCase()}.`};
      }
      const high=s.swingHighs.at(-1),low=s.swingLows.at(-1);
      const challenged=s.trend==='up'&&s.lastCloseVsLow==='below'||s.trend==='down'&&s.lastCloseVsHigh==='above';
      const row={timeframe:tf,role,bias:'undetermined',verdict:'No clear trend',phase:'Unestablished structure',reading:'',evidence:'',changeCondition:''};
      const priorHigh=s.swingHighs.at(-2),priorLow=s.swingLows.at(-2);
      const swings=s.swingHighs.length===2&&s.swingLows.length===2;
      const highSequence=swings?high.price>priorHigh.price?'higher highs':high.price<priorHigh.price?'lower highs':'equal highs':null;
      const lowSequence=swings?low.price>priorLow.price?'higher lows':low.price<priorLow.price?'lower lows':'equal lows':null;
      row.evidence=`Last completed ${name} close ${price(f.lastClose)}. `+(swings?`Confirmed ${highSequence} (${price(priorHigh.price)} → ${price(high.price)}) and ${lowSequence} (${price(priorLow.price)} → ${price(low.price)}).`:'Two confirmed swing highs and two confirmed swing lows are not established in this sample.');
      if(challenged){
        const wasUp=s.trend==='up',reference=wasUp?low:high;
        row.bias='mixed';row.verdict=wasUp?'Bullish structure challenged':'Bearish structure challenged';row.phase='Prior structure challenged';
        row.reading=`${name}: the prior ${wasUp?'bullish':'bearish'} structure is challenged. The completed close is ${wasUp?'below':'above'} the latest confirmed swing ${wasUp?'low':'high'} at ${price(reference.price)}; an opposite trend is not yet established.`;
        row.changeCondition=`The ${name} close has already crossed ${price(reference.price)}. New completed candles and confirmed swings are needed to assess recovery or a reversal.`;
      }else if(s.trend==='up'||s.trend==='down'){
        const up=s.trend==='up';row.bias=up?'bullish':'bearish';row.verdict=up?'Bullish structure':'Bearish structure';row.phase='Directional structure';
        row.reading=`${name}: ${up?'bullish':'bearish'} structure. ${up?'Higher highs and higher lows':'Lower highs and lower lows'} remain intact at the saved close.`;
        row.changeCondition=`A completed ${name} close ${up?'below':'above'} the latest confirmed swing ${up?'low':'high'} at ${price((up?low:high).price)} would challenge this structure; it would not by itself confirm the opposite trend.`;
      }else if(s.trend==='mixed'){
        row.bias='mixed';row.verdict='Mixed structure';
        row.phase=highSequence==='lower highs'&&lowSequence==='higher lows'?'Compressing swings':highSequence==='higher highs'&&lowSequence==='lower lows'?'Expanding swings':'Mixed swings';
        row.reading=`${name}: mixed structure. ${highSequence[0].toUpperCase()+highSequence.slice(1)} and ${lowSequence} do not establish a consistent direction.`;
        row.changeCondition=`New confirmed ${name} high and low pairs would need to establish the same direction before calling this structure bullish or bearish.`;
      }else{
        row.reading=`${name}: no established swing trend. The sample does not yet contain two confirmed high and low pairs.`;
        row.changeCondition=`Wait for sufficient confirmed ${name} high and low pairs; recent price displacement alone cannot establish a swing trend.`;
      }
      if(f.lastClosePosition==='above'||f.lastClosePosition==='below')row.evidence+=` The close is ${f.lastClosePosition} the prior 20-bar ${f.lastClosePosition==='above'?'high':'low'} (${price(f.lastClosePosition==='above'?f.prior20High:f.prior20Low)}). This range break does not by itself confirm continuation.`;
      return row;
    };
    const frames=INTRADAY_TIMEFRAMES.map(frame),[context,active,setup,timing]=frames;
    const available=!!e?.available&&frames.every(f=>f.bias!=='unavailable');
    const out={version:1,source:'calculated-rules',method:'intraday-structure-hierarchy-v1',profile:'intraday-v1',available,relationship:'incomplete',frames,
      reading:'',support:'',concern:'',governing:'4H sets context; 1H describes active structure; 15m describes the setup; 5m refines timing. Lower frames do not replace higher context.',setupCondition:'',setupInvalidation:'',contextInvalidation:'',
      limits:'Calculated from completed candles at the saved cutoff using confirmed two-left/two-right swings within 120 bars. Swing confirmation lags price. This is a structure assessment, not a connected AI response, entry signal or probability of profit.'};
    const c=direction(context.bias),a=direction(active.bias),s=direction(setup.bias),t=direction(timing.bias);
    if(!available){
      const missing=frames.filter(f=>f.bias==='unavailable').map(f=>f.timeframe.toUpperCase()).join(', ');
      out.reading=`Incomplete hierarchy: ${missing||'required timeframe evidence'} unavailable. A full four-timeframe conclusion cannot be made.`;
      out.support=frames.filter(f=>f.bias!=='unavailable').map(f=>`${f.timeframe.toUpperCase()}: ${f.verdict.toLowerCase()}`).join('; ')||'No timeframe has sufficient validated evidence.';
      out.concern='Available timeframe readings remain useful individually, but missing context or timing must not be treated as agreement.';
    }else if(!c){
      out.relationship=context.bias==='mixed'?'mixed':'undetermined';
      out.reading=context.bias==='mixed'?'Mixed 4H context. Lower-timeframe direction does not establish a clear higher-timeframe trend.':'4H trend is not established. The overall direction remains undetermined.';
      out.support=`4H: ${context.verdict.toLowerCase()}. 1H: ${active.verdict.toLowerCase()}; 15m: ${setup.verdict.toLowerCase()}; 5m: ${timing.verdict.toLowerCase()}.`;
      out.concern='A directional move on a lower timeframe can exist inside unresolved higher structure; it is not enough to call the whole hierarchy aligned.';
    }else if(a&&a!==c){
      out.relationship='conflicting';
      out.reading=`${c[0].toUpperCase()+c.slice(1)} 4H context conflicts with ${a} 1H structure. Treat the active move as counter to context.`;
      out.support=`4H remains ${c}; 1H is ${a}. The 15m setup is ${setup.verdict.toLowerCase()} and 5m timing is ${timing.verdict.toLowerCase()}.`;
      out.concern='The lower frames cannot resolve this higher-timeframe conflict by outnumbering 4H. Neither a completed reversal nor continuation is established by this relationship alone.';
    }else if(!a){
      out.relationship='mixed';out.reading=`${c[0].toUpperCase()+c.slice(1)} 4H context, unresolved 1H structure. The setup has only partial support.`;
      out.support=`4H: ${context.verdict.toLowerCase()}. 1H: ${active.verdict.toLowerCase()}.`;
      out.concern=`The active 1H structure needs clarification before calling the hierarchy aligned. 15m is ${setup.verdict.toLowerCase()}; 5m is ${timing.verdict.toLowerCase()}.`;
    }else if(s===c&&t===c){
      out.relationship='aligned';out.reading=`${c[0].toUpperCase()+c.slice(1)} across 4H, 1H, 15m and 5m. Structure aligns; an entry is not established.`;
      out.support=`4H context and 1H active structure are ${c}. The 15m setup and 5m timing agree with that direction.`;
      out.concern='Alignment describes the saved structure. It does not establish follow-through, a valid strategy trigger or acceptable execution risk.';
    }else if(s&&s!==c){
      out.relationship='compatible-pullback';out.reading=`Possible ${s} pullback within ${c} 4H and 1H structure. Continuation is unconfirmed.`;
      out.support=`4H context and 1H active structure remain ${c}, while 15m points ${s}.`;
      out.concern=t===s?`5m agrees with the countertrend 15m move. It could deepen or become a reversal attempt; a pullback resolution is not confirmed.`:t===c?`5m points back toward ${c} context, but the 15m structure has not aligned. Timing alone does not confirm a recovery.`:`5m timing is unresolved. The lower move could remain a pullback or develop further against context.`;
    }else{
      out.relationship='mixed';out.reading=s===c?`${c[0].toUpperCase()+c.slice(1)} context and setup, but 5m timing ${t?'opposes them':'is unresolved'}. Alignment is partial.`:`${c[0].toUpperCase()+c.slice(1)} 4H and 1H structure, but the 15m setup is unresolved. Alignment is partial.`;
      out.support=`4H context and 1H active structure agree: ${c}. 15m: ${setup.verdict.toLowerCase()}; 5m: ${timing.verdict.toLowerCase()}.`;
      out.concern='A timing difference or unresolved setup must stay visible. It does not automatically invalidate higher-timeframe structure.';
    }
    out.setupInvalidation=setup.changeCondition;out.contextInvalidation=context.changeCondition;
    const setupFacts=e?.frames?.['15m'];
    if(s&&setupFacts){
      const up=s==='bullish',bound=up?setupFacts.prior20High:setupFacts.prior20Low,met=up?setupFacts.lastClose>bound:setupFacts.lastClose<bound;
      out.setupCondition=`The completed 15m close ${met?'has already cleared':'has not cleared'} the prior 20-bar ${up?'high':'low'} at ${price(bound)}. ${met?'This is an observed range break':'A close beyond that bound is a reference to watch'}, not a validated entry trigger.`;
    }else out.setupCondition=`No directional 15m trigger is established: ${setup.verdict.toLowerCase()}. Reassess with new completed candles rather than infer an entry from lower timing.`;
    return freeze(out);
  }
  return {extract,interpret,version:VERSION,minimumBars:MINIMUM_BARS};
});
