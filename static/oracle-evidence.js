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
  return {extract,version:VERSION,minimumBars:MINIMUM_BARS};
});
