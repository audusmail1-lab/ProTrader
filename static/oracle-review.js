/*
 * Oracle structured reviewer, v1. A transparent teaching rubric, not an AI
 * prediction, professional competency test, or validated trading edge.
 *
 * Data contract deliberately has no ARIA input. Review uses only a frozen
 * hypothesis and independently obtained completed OHLC histories. A subsequent
 * comparison may use ARIA, but cannot alter this first pass.
 *
 * Bounded assumptions (documented so every finding is reproducible):
 * - Context describes the latest 20 completed bars. Close displacement is last
 *   close minus first close; it is not an estimate of future trend or momentum.
 * - Continuation expects that displacement on the selected and mapped higher
 *   interval to have the proposed direction. Range reversal explicitly permits
 *   an opposing higher interval; it requires a rejection of the prior 20-bar
 *   boundary in the final closed candle. Breakout expects the latest close to
 *   be beyond the prior 20-bar boundary. Conditional plans may wait for these
 *   observations; those remain unresolved conditions, not confirmations.
 * - Visible-structure targets must sit within 10% of the prior 20-bar boundary
 *   (or one recent mean candle range, whichever is smaller). This is a stated
 *   teaching convention, not a universal market rule. Fixed multiples describe
 *   arithmetic only, not evidence that a target will be reached.
 * - A claimed closed-confirmation entry must be within one recent mean candle
 *   range of the latest completed close. Further prices need a conditional
 *   entry declaration. This is a disclosed teaching rule, not a fill model.
 * - Risk is linear paper-model arithmetic in USD; costs are total estimated
 *   round-trip USD for the whole quantity. Gaps, slippage and actual fills are
 *   not predicted. A violated declared/configured budget is an arithmetic
 *   constraint on this paper plan; nothing here locks or submits execution.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.ProTraderOracle = api;
})(typeof globalThis === 'object' ? globalThis : this, function () {
  'use strict';
  const methodVersion = 'structured-review-1.0.0';
  const intervals = Object.freeze({'1m':60,'5m':300,'15m':900,'1h':3600,'4h':14400,'1d':86400});
  const higherTimeframe = Object.freeze({'1m':'15m','5m':'1h','15m':'1h','1h':'4h','4h':'1d'});
  const methods = Object.freeze(['continuation','breakout','range-reversal','other']);
  const finite = value => typeof value === 'number' && Number.isFinite(value);
  const positive = value => finite(value) && value > 0;
  const nonnegative = value => finite(value) && value >= 0;
  const text = value => typeof value === 'string' ? value.trim() : '';
  const readable = value => text(value).length >= 12;
  // Preserve malformed numeric inputs until validation. A JSON round trip
  // would silently turn NaN/Infinity into ordinary missing null and could let
  // a student assumption replace an invalid captured account constraint.
  const clone = value => Array.isArray(value) ? value.map(clone) : value && typeof value==='object' ?
    Object.fromEntries(Object.entries(value).map(([key,item])=>[key,clone(item)])) : value;
  function freeze(value) {
    if (value && typeof value === 'object') {Object.freeze(value);Object.values(value).forEach(freeze);}
    return value;
  }
  const numberText = n => Number(n.toPrecision(7)).toString();
  const usd = n => '$' + n.toFixed(2);
  const reference = (snapshot,tf,time) => `${snapshot.id || 'unidentified'}:${tf}:${time}`;

  function review(hypothesis, snapshot) {
    // Clone before calculation: subsequent caller mutations cannot rewrite the
    // explanation or values that were actually assessed.
    const h = clone(hypothesis || {}), s = clone(snapshot || {});
    const result = {version:1,methodVersion,snapshotId:s.id || null,hypothesisId:h.id || null,
      assessment:'Insufficient information',constraints:[],concerns:[],unknowns:[],facts:[],whatChanges:[],
      metrics:{},evidenceRefs:[],limitations:[
        'Rule-based teaching review; no win probability, predictive validation or AI assessment.',
        'Free-text reasoning is retained for reflection, not semantically verified. Supported means only that these bounded checks found no material issue or essential unknown.',
        'OHLC describes traded prices; it does not reveal hidden orders, institutional intent or future price.',
        'Risk uses a declared paper model and estimated costs. Actual broker specifications, gaps, slippage and fills may differ.',
        'Paper guidance is reviewed here; this module does not enforce limits or submit orders.'
      ]};
    const add = (group,id,area,title,fact,relevance,resolution,extra={}) => {
      const finding={id,area,title,fact,relevance,resolution,...extra};
      result[group].push(finding);
      if ((group==='constraints' || group==='concerns' || group==='unknowns') && resolution)
        result.whatChanges.push({...finding,id:'change-'+id,title:'Resolve: '+title});
      return finding;
    };
    const unknown = (id,area,title,fact,relevance,resolution,extra={}) => add('unknowns',id,area,title,fact,relevance,resolution,{essential:true,...extra});
    const concern = (id,area,title,fact,relevance,resolution,extra={}) => add('concerns',id,area,title,fact,relevance,resolution,extra);
    const constraint = (id,title,fact,relevance,resolution,area='risk') => add('constraints',id,area,title,fact,relevance,resolution,{essential:true,material:true});
    const fact = (id,area,title,observed,relevance,resolution='',extra={}) => add('facts',id,area,title,observed,relevance,resolution,extra);
    const primaryTF=h.timeframe, higherTF=higherTimeframe[primaryTF];
    const direction=h.action==='long'?1:h.action==='short'?-1:0, trading=!!direction;
    if (!higherTF) unknown('timeframe','context','Unsupported horizon',`The selected timeframe ${text(primaryTF) || '(missing)'} is outside the supported mappings.`,
      'This reviewer needs a declared interval and a defined higher context.','Select 1m, 5m, 15m, 1h or 4h.');
    if (!['long','short','wait'].includes(h.action)) unknown('action','logic','Decision missing','No supported direction or deliberate wait is recorded.',
      'An assessment must relate to the student’s decision.','Record long, short or wait before reviewing.');
    if (!methods.includes(h.method) || h.method==='other') unknown('method','context','Method outside the rubric',
      `Method: ${text(h.method) || '(missing)'}. Arbitrary strategy prose is not interpreted by these rules.`,
      'The relevance of context and invalidation changes with the intended method.','Use a supported method with its stated assumptions, or seek a separate sourced review.');
    if (!s.id || !positive(s.asOf) || !positive(s.capturedAt)) unknown('snapshot','evidence','Snapshot reference incomplete',
      'Snapshot ID, decision cutoff or capture time is missing.','Past evidence cannot be reproduced without its identity and cutoff.','Capture a new, identified market-data snapshot.');
    if (!text(h.symbol) || h.symbol!==s.symbol) unknown('symbol','evidence','Instrument mismatch',
      `Hypothesis instrument ${text(h.symbol) || '(missing)'} differs from snapshot instrument ${text(s.symbol) || '(missing)'}.`,
      'Evidence from another instrument cannot support this hypothesis.','Capture the hypothesis instrument again; keep the original review unchanged.');
    if (positive(s.asOf) && positive(s.capturedAt) && s.asOf>s.capturedAt) unknown('cutoff','evidence','Future decision cutoff',
      'The decision cutoff is later than the snapshot capture time.','A captured forming bar cannot be promoted to a completed bar as time passes.','Capture new evidence with its cutoff at or before capture.');
    if (!readable(h.observation)) unknown('observation','logic','Observation missing','A sufficiently specific observable fact has not been recorded.',
      'A prediction alone cannot be checked against frozen prices.','Write an observable price, close, level or interval before an interpretation.');
    if (!readable(h.reasoning)) unknown('reasoning','logic','Reasoning missing','The hypothesis does not explain how the observation supports the decision.',
      'This review does not grade a direction by itself.','Explain the link between an observed fact and the proposed decision.');
    if (!positive(h.thesisLevel)) unknown('thesis-level','logic','Thesis reference missing','No positive thesis reference price is supplied.',
      'The recorded interpretation needs an observable reference to test its invalidation.','Identify the price level the thesis depends on.');

    function inspect(tf) {
      if (!tf) return null;
      const row=s.series && s.series[tf], seconds=intervals[tf];
      const absent = (id,title,observed,resolution) => {unknown(id+'-'+tf,'evidence',title,observed,
        `${tf} completed candles are required for this declared horizon and its context.`,resolution,{refs:[`${s.id || 'unidentified'}:${tf}`]});return null;};
      if (!row || row.status!=='ready' || !Array.isArray(row.candles)) return absent('history','History unavailable',
        `${tf}: ${text(row && row.error) || 'No completed history available.'}`,'Retrieve this interval from the identified instrument feed.');
      if (!text(row.source)) return absent('source','Source missing',`${tf} history has no identified source.`,'Retrieve history with a source and capture timestamp.');
      if (!positive(row.capturedAt) || row.capturedAt<s.asOf) return absent('capture','History capture cannot support cutoff',
        `${tf} history was not captured at or after the decision cutoff.`,'Use a cutoff at capture time or retrieve final candles again.');
      const bars=row.candles;
      for (let i=0;i<bars.length;i++) {
        const b=bars[i];
        if (!b || !['time','open','high','low','close'].every(k=>finite(b[k])) || !Number.isInteger(b.time) || b.time<=0 ||
            b.low<=0 || b.high<Math.max(b.open,b.close,b.low) || b.low>Math.min(b.open,b.close) ||
            (i && (b.time-bars[i-1].time<seconds || (b.time-bars[i-1].time)%seconds!==0)))
          return absent('integrity','Candle interval or OHLC integrity failed',`${tf} has malformed, out-of-order or incorrectly spaced candles.`,
            'Retrieve correct interval history; do not relabel a finer series.');
      }
      const cutoff=Math.min(s.asOf,row.capturedAt),closed=bars.filter(b=>b.time+seconds<=cutoff);
      if (closed.length<30) return absent('insufficient','Insufficient completed history',`${tf} has ${closed.length}/30 required completed candles.`,
        'Obtain at least 30 completed candles, including the prior 20-bar structure window.');
      const last=closed.at(-1),closedAt=last.time+seconds,age=s.asOf-closedAt;
      if (age>Math.max(180,seconds*2)) return absent('stale','History stale or market closed',
        `${tf} latest completed bar ended ${Math.round(age)} seconds before cutoff. No current-context conclusion is made.`,
        'Review fresh completed history when the feed and market are available.');
      const prior=closed.slice(-21,-1),window=closed.slice(-20),low=Math.min(...prior.map(b=>b.low)),high=Math.max(...prior.map(b=>b.high));
      const displacement=last.close-window[0].close, meanRange=window.reduce((sum,b)=>sum+b.high-b.low,0)/window.length;
      const refs=[reference(s,tf,last.time),reference(s,tf,prior[0].time)];
      result.evidenceRefs.push(...refs);
      const structure={timeframe:tf,closedAt,bars:closed.length,lastClose:last.close,lastOpen:last.open,lastHigh:last.high,lastLow:last.low,
        priorLow:low,priorHigh:high,displacement,meanRange,excludedBars:bars.length-closed.length};
      result.metrics[tf]=structure;
      fact('structure-'+tf,'context',tf+' observed structure',
        `Latest completed close ${numberText(last.close)}; prior 20-bar low/high ${numberText(low)} / ${numberText(high)}; last 20 closes displaced ${numberText(displacement)}.`,
        'These are observed bounds and close displacement, not forecasts or proof of support, resistance or a trend.', '',{refs});
      fact('quality-'+tf,'evidence',tf+' evidence cutoff',
        `${row.source}; ${closed.length} completed bars through ${closedAt}; ${bars.length-closed.length} forming/future bars excluded.`,
        'Only bars completed at the frozen cutoff enter this assessment.','', {refs});
      return structure;
    }
    const primary=inspect(primaryTF),higher=inspect(higherTF);
    if (primary) {
      const refs=[reference(s,primaryTF,primary.closedAt-intervals[primaryTF])];
      if (positive(h.thesisLevel) && (h.thesisLevel<primary.priorLow-primary.meanRange || h.thesisLevel>primary.priorHigh+primary.meanRange))
        concern('level-evidence','logic','Thesis reference outside visible structure',
          `Thesis level ${numberText(h.thesisLevel)} lies beyond the prior ${primaryTF} 20-bar range plus one mean candle range.`,
          'The available window does not show a test of this level.','Supply a longer sourced window that contains the level, or explain a reference visible in this snapshot.',{material:true,refs});
      if (trading && h.method==='continuation') {
        if (primary.displacement*direction<=0) concern('primary-continuation','context','Selected interval does not meet continuation assumption',
          `${primaryTF} close displacement is ${numberText(primary.displacement)}, opposing or flat against the proposed ${h.action}.`,
          'This bounded continuation method expects displacement in the proposed direction. This is a method mismatch, not a prediction.',
          `Revisit after the ${primaryTF} completed-bar window displaces ${direction>0?'upward':'downward'}, or deliberately change the method and explain why.`,{material:true,refs});
      }
      if (trading && h.entryCondition==='closed-confirmation' && positive(h.plan && h.plan.entry) &&
          Math.abs(h.plan.entry-primary.lastClose)>primary.meanRange)
        concern('entry-evidence','logic','Entry is away from the observed confirmation',
          `Proposed entry ${numberText(h.plan.entry)} is more than one mean ${primaryTF} candle range (${numberText(primary.meanRange)}) from the latest completed close ${numberText(primary.lastClose)}.`,
          'This snapshot does not demonstrate an immediate closed-confirmation entry at that price. This distance rule is a disclosed teaching convention.',
          'Label a pending price entry as conditional, or capture fresh evidence that shows the proposed price.',{material:true,refs});
      if (trading && h.method==='breakout') {
        const boundary=direction>0?primary.priorHigh:primary.priorLow,confirmed=direction>0?primary.lastClose>boundary:primary.lastClose<boundary;
        if (!confirmed) {
          const material=h.entryCondition==='closed-confirmation';
          concern('breakout-confirmation','logic',material?'Claimed breakout is not closed-confirmed':'Breakout remains conditional',
            `Latest ${primaryTF} close ${numberText(primary.lastClose)} has not closed ${direction>0?'above':'below'} prior 20-bar boundary ${numberText(boundary)}.`,
            material?'The declared closed-confirmation entry is contradicted by this snapshot.':'A pending entry is an assumption; the available bars do not establish the trigger.',
            `Wait for a new completed ${primaryTF} close ${direction>0?'above':'below'} the newly observed boundary, then review a new snapshot.`,{material,essential:!material,refs});
        } else fact('breakout-observed','logic','Boundary close observed',
          `${primaryTF} closed at ${numberText(primary.lastClose)}, ${direction>0?'above':'below'} the prior boundary ${numberText(boundary)}.`,
          'This meets only the declared close-breakout observation; it does not establish that continuation will follow.','',{refs});
      }
      if (trading && h.method==='range-reversal') {
        const rejected=direction>0?primary.lastLow<=primary.priorLow && primary.lastClose>primary.priorLow && primary.lastClose>primary.lastOpen:
          primary.lastHigh>=primary.priorHigh && primary.lastClose<primary.priorHigh && primary.lastClose<primary.lastOpen;
        if (!rejected) concern('range-rejection','logic','Range rejection has not been observed',
          `The final completed ${primaryTF} candle does not touch the prior ${direction>0?'low':'high'}, close back inside, and close in the proposed direction.`,
          'Those are the explicit assumptions for this bounded range-reversal exercise; a different reversal method is not assessed.',
          'Wait for a completed candle that meets the stated boundary-rejection conditions, or revise the declared method with a reason.',
          {material:h.entryCondition==='closed-confirmation',essential:h.entryCondition!=='closed-confirmation',refs});
        else fact('range-observed','logic','Boundary rejection observed',
          `The final ${primaryTF} candle tested the prior ${direction>0?'low':'high'}, closed back inside and closed in the proposed direction.`,
          'This meets the stated range-reversal observation only. A later break of the boundary remains possible.','',{refs});
      }
      if (trading && h.targetBasis==='visible-structure' && positive(h.plan && h.plan.target)) {
        const boundary=direction>0?primary.priorHigh:primary.priorLow,tolerance=Math.min((primary.priorHigh-primary.priorLow)*.1,primary.meanRange);
        if (Math.abs(h.plan.target-boundary)>tolerance) concern('target-structure','logic','Target not supported by the visible boundary',
          `Target ${numberText(h.plan.target)} differs from the relevant prior ${primaryTF} boundary ${numberText(boundary)} by more than the stated window tolerance ${numberText(tolerance)}.`,
          'The declared visible-structure target is not demonstrated by the available window.','Use a sourced structure reference in view, or label the target as a fixed-multiple assumption.',{material:true,refs});
        else fact('target-structure-observed','logic','Target reference visible',`Target ${numberText(h.plan.target)} is near prior ${primaryTF} boundary ${numberText(boundary)}.`,
          'A visible price boundary supplies a reference, not evidence that the market will reach it.','',{refs});
      }
    }
    if (trading && higher) {
      const opposite=higher.displacement*direction<0,flat=higher.displacement===0,refs=[reference(s,higherTF,higher.closedAt-intervals[higherTF])];
      if (opposite || flat) {
        const material=h.method==='continuation';
        concern('higher-context','context',material?'Higher interval conflicts with continuation assumption':'Higher interval differs from proposed direction',
          `${higherTF} 20-close displacement is ${numberText(higher.displacement)}; proposed action is ${h.action} on ${primaryTF}.`,
          material?'Continuation here explicitly assumes matching higher-interval displacement.':'Range reversal or breakout can deliberately oppose this context; the difference is contextual, not an automatic veto.',
          material?`Review after fresh ${higherTF} completed closes align, or revise the method and explain the conflict.`:
            'Retain or revise the idea with an explicit reason for accepting this higher-interval context; recheck the declared invalidation.',{material,refs});
      } else fact('higher-aligned','context','Higher interval direction described',
        `${higherTF} 20-close displacement ${numberText(higher.displacement)} has the proposed ${h.action} sign.`,
        'This satisfies the bounded context assumption only; it is not another independent vote from a separate market.','',{refs});
    }
    if (trading) {
      const inv=h.invalidation || {},p=h.plan || {};
      if (!['closed-confirmation','conditional'].includes(h.entryCondition)) unknown('entry-condition','logic','Entry assumption missing',
        'No supported entry condition is recorded.','A pending plan and an observed closed confirmation require different interpretation.','Declare closed confirmation or a conditional entry.');
      if (h.entryCondition==='conditional') fact('conditional-entry','logic','Entry is conditional',
        'The student declared a conditional entry.','The plan records assumptions before a trigger; this review is not permission to enter.');
      if (!['visible-structure','fixed-multiple','other'].includes(h.targetBasis) || h.targetBasis==='other') unknown('target-basis','logic','Target basis not assessed',
        'The proposed target has no supported stated basis.','Price geometry alone does not explain why a target was chosen.','Choose a visible boundary reference or explicitly declare a fixed-multiple arithmetic assumption.');
      if (h.targetBasis==='fixed-multiple') fact('target-assumption','logic','Target is an arithmetic assumption',
        'The target is labelled a fixed multiple.','A reward/risk multiple is arithmetic, not evidence that price will reach the target.');
      if (!positive(inv.price) || !readable(inv.reason) || !['close-below','close-above'].includes(inv.condition)) unknown('invalidation','logic','Testable invalidation incomplete',
        'A valid invalidation price, close condition or explanation is missing.','The idea needs a condition that could falsify it.','Record a close-above/close-below condition, its price and its relation to the thesis.');
      if (positive(inv.price)) {
        if (['close-below','close-above'].includes(inv.condition) && ((direction>0 && inv.condition!=='close-below') || (direction<0 && inv.condition!=='close-above')))
          constraint('invalidation-direction','Invalidation contradicts the declared method',
            `${h.action} idea uses ${inv.condition} ${numberText(inv.price)}.`,
            'For the supported long/short continuation, breakout and range methods, invalidation must challenge the idea on the adverse side.',
            `Use ${direction>0?'close-below':'close-above'} with a reason linked to the thesis, or choose a separately assessed method.`,'logic');
        if (positive(p.entry) && (p.entry-inv.price)*direction<=0) constraint('invalidation-entry','Invalidation is on the wrong side of entry',
          `Entry ${numberText(p.entry)} and invalidation ${numberText(inv.price)} do not put invalidation on the adverse side of a ${h.action}.`,
          'The plan cannot consistently use this invalidation as its adverse failure boundary.','Revise the idea or planned entry and explain the observable failure condition.','logic');
        if (positive(h.thesisLevel) && (h.thesisLevel-inv.price)*direction<0) constraint('invalidation-thesis','Invalidation does not defend the declared thesis level',
          `Thesis level ${numberText(h.thesisLevel)} lies beyond invalidation ${numberText(inv.price)} on the adverse side.`,
          'The supported methods require invalidation at or beyond the adverse side of the thesis reference; this plan exits the thesis before that level is challenged.',
          'Link invalidation to the recorded thesis reference, or revise the reference and explain why.','logic');
        if (positive(p.stop) && (inv.price-p.stop)*direction<0) constraint('stop-invalidation','Stop precedes the stated thesis invalidation',
          `Stop ${numberText(p.stop)} would be reached before invalidation level ${numberText(inv.price)}.`,
          'This stop does not cover the stated adverse thesis boundary.','Revise size, stop or thesis consistently; do not move invalidation merely to fit a budget.','logic');
        if (primary && ((inv.condition==='close-below' && primary.lastClose<=inv.price) || (inv.condition==='close-above' && primary.lastClose>=inv.price)))
          concern('invalidation-met','logic','Snapshot already meets the invalidation condition',
            `Latest ${primaryTF} close ${numberText(primary.lastClose)} meets ${inv.condition} ${numberText(inv.price)} (including the boundary).`,
            'The current hypothesis needs a reset condition or withdrawal before this evidence can support it.','Withdraw or revise with a reason, or observe a clearly declared new setup on fresh completed bars.',{material:true});
      }
      if (!['entry','stop','target','quantity'].every(k=>positive(p[k]))) unknown('plan-input','risk','Paper plan incomplete',
        'Entry, stop, target or quantity is missing or nonpositive.','Deterministic risk and geometry need all four positive inputs.','Supply the proposed paper entry, stop, target and quantity.');
      if (positive(p.entry) && positive(p.stop) && (p.entry-p.stop)*direction<=0) constraint('stop-side','Stop is not on the loss side',
        `For ${h.action}, entry is ${numberText(p.entry)} and stop is ${numberText(p.stop)}.`,
        'A zero-distance or reward-side stop cannot define planned loss.','Place a consistent adverse stop and reconsider quantity against the budget.');
      if (positive(p.entry) && positive(p.target) && (p.target-p.entry)*direction<=0) constraint('target-side','Target is not on the reward side',
        `For ${h.action}, entry is ${numberText(p.entry)} and target is ${numberText(p.target)}.`,
        'This target has no positive planned reward in the declared direction.','Revise or withdraw the plan with a reason.');
      riskReview(h,s,result,{unknown,constraint,fact,concern});
    } else if (h.action==='wait') {
      const wait=h.wait || {};
      if (!readable(wait.reason) || (!readable(wait.condition) && !['close-above','close-below'].includes(wait.condition)) || !positive(wait.price)) unknown('wait-condition','logic','Revisit condition incomplete',
        'The wait decision lacks a specific reason, observable condition or price.','Waiting is a valid outcome when it has a deliberate review condition.','Record why you are waiting and exactly what observed price condition would make you look again.');
      else fact('deliberate-wait','logic','Deliberate wait recorded',
        `Revisit reference ${numberText(wait.price)}; ${wait.condition}`,
        'A deliberate wait needs no order or position sizing. This is not graded as inferior to taking a trade.');
      result.metrics.risk=null;
    }
    unknown('execution-scope','risk','Additional execution constraints not assessed',
      'This snapshot supplies no verified margin requirement, free-funds check, cross-position correlation model or liquidity/fill-depth source.',
      'The paper review cannot establish order acceptability, financing capacity, correlated portfolio loss or the availability of a fill at a quoted price. A deliberate wait does not require an execution check.',
      'Check sourced broker margin/free-funds information, portfolio exposures and execution conditions separately before any real execution decision.',{essential:false});
    unknown('unsupported-context','evidence','External context not assessed',
      'No sourced news calendar, macro-event, order-flow, hidden-liquidity or validated-edge evidence is supplied.',
      'Candles cannot establish these claims; the review is bounded to the observed prices and declared paper assumptions.',
      'Consult an identified relevant source separately if the hypothesis depends on it.',{essential:false});
    const material=result.constraints.length || result.concerns.some(f=>f.material),incomplete=result.unknowns.some(f=>f.essential) || result.concerns.some(f=>f.essential);
    result.assessment=material?'Material concern':incomplete?'Insufficient information':'Supported on available evidence';
    if (!material && !incomplete) result.whatChanges.push({id:'change-monitor',area:'logic',title:'What could change this assessment?',
      fact:'The stated assumptions are supported only at the recorded cutoff.',relevance:'New evidence may contradict this hypothesis without changing the original review.',
      resolution:trading?`Review a new snapshot after the declared ${h.invalidation.condition} ${numberText(h.invalidation.price)}, a changed ${higherTF} context, or a changed cost/risk assumption.`:
        `Review a new snapshot when the declared revisit condition at ${numberText(h.wait.price)} is observed.`});
    return freeze(result);
  }

  function riskReview(h,s,result,{unknown,constraint,fact,concern}) {
    const p=h.plan || {},spec=s.spec,account=s.account || {},direction=h.action==='long'?1:-1;
    const q=s.quote;
    if (!q || !positive(q.bid) || !positive(q.ask) || q.ask<q.bid || !positive(q.time) || !text(q.source) || q.time>s.asOf || s.asOf-q.time>30)
      unknown('quote','risk','Executable quote unavailable',
        'A sourced bid/ask at or before cutoff and no older than 30 seconds is unavailable or inconsistent.',
        'A candle close does not establish spread or the price at which a plan could be executed.','Obtain a current sourced bid/ask; retain this review as unknown.');
    else {
      result.metrics.quote={bid:q.bid,ask:q.ask,spread:q.ask-q.bid,time:q.time,source:q.source};
      fact('quote-observed','risk','Quote at cutoff',`Bid ${numberText(q.bid)} / ask ${numberText(q.ask)} from ${q.source}; age ${Math.round(s.asOf-q.time)} seconds.`,
        'The spread is observed. It is not a guarantee of a later fill or inclusion in the cost estimate.');
    }
    const validSpec=spec && positive(spec.valuePerPriceUnit) && positive(spec.quantityStep) && positive(spec.minQuantity) &&
      positive(spec.maxQuantity) && spec.minQuantity<=spec.maxQuantity && spec.currency==='USD' && text(spec.source);
    if (!validSpec) unknown('specification','risk','Linear paper specification unavailable',
      'A sourced USD value-per-price-unit, quantity step and bounds are not all supplied.',
      'Quantity alone cannot be converted into a meaningful monetary loss.','Supply the explicit paper model; verify actual broker contract terms separately.');
    else {
      fact('paper-specification','risk','Paper model assumption',
        `${spec.source}: $${numberText(spec.valuePerPriceUnit)} per price unit per quantity; quantity ${numberText(spec.minQuantity)}–${numberText(spec.maxQuantity)} in steps of ${numberText(spec.quantityStep)}.`,
        'The calculation depends on these model assumptions; they are not verified broker contract specifications.');
      if (positive(p.quantity) && (p.quantity<spec.minQuantity || p.quantity>spec.maxQuantity || Math.abs(p.quantity/spec.quantityStep-Math.round(p.quantity/spec.quantityStep))>1e-7))
        constraint('quantity','Quantity violates the supplied paper model',`Quantity ${numberText(p.quantity)} does not fit the model’s bounds or step.`,
          'The proposed quantity cannot be represented consistently in this paper model.','Use a representable quantity within the stated model bounds, then recalculate risk.');
    }
    if (!nonnegative(p.cost)) unknown('cost','risk','Cost estimate missing',
      'Total round-trip USD cost is unknown. No zero-cost assumption was inserted.',
      'Costs change planned loss, reward and budget headroom.','Enter an explicit total cost assumption for this quantity, including estimated spread/fees; zero requires a deliberate paper assumption.');
    else fact('cost-assumption','risk','Declared total cost',`${usd(p.cost)} total estimated round-trip cost for this quantity.`,
      'This is a student-declared estimate; actual spread, commission and slippage may differ.');
    const values={},provenance={};
    for (const key of ['openRisk','realizedLoss','perIdeaLimit','combinedLimit','dailyLossLimit']) {
      const a=p[key],b=account[key],isLimit=key.endsWith('Limit');
      // The capture service preserves invalid cap provenance explicitly before
      // JSON persistence can turn NaN/Infinity into null. A marked null remains
      // an invalid known constraint, not an absent value open to substitution.
      const invalidMarker=isLimit && Array.isArray(account.invalidLimits) && account.invalidLimits.includes(key);
      const invalidCaptured=invalidMarker || b!=null && !nonnegative(b);
      if (invalidCaptured) unknown('invalid-captured-'+key,'risk','Captured account constraint is invalid: '+key,
        invalidMarker?`The captured source marked ${key} as invalid before serialization; the stored value ${String(b)} is not a usable account limit.`:
          `Captured ${key} is ${String(b)}, rather than a finite nonnegative USD amount.`,
        'An invalid known account constraint cannot be replaced by a more permissive student assumption.',
        'Retrieve or correct the captured account evidence; retain an insufficient-information result while this value is invalid.');
      if (isLimit) {
        // Zero is a known exhausted budget, never an absent/disabled limit.
        const candidates=[a,b].filter(nonnegative);values[key]=invalidCaptured?null:candidates.length?Math.min(...candidates):null;
        if (a!=null && !nonnegative(a)) constraint('invalid-'+key,'Invalid declared risk limit',`${key} is not a nonnegative finite USD limit.`,
          'A negative or nonfinite budget cannot waive a plan check. Zero means no remaining risk allowance.','Supply a finite nonnegative paper limit; zero permits no additional planned risk.');
        if (nonnegative(a) && nonnegative(b) && a>b) concern('limit-override-'+key,'risk','Declared limit exceeds configured paper guidance',
          `Declared ${key} ${usd(a)} exceeds configured ${usd(b)}; the stricter value ${usd(b)} is used.`,
          'The reviewer cannot silently waive configured guidance through a changed plan assumption.','Revise the plan against the displayed guidance; configuration changes belong to a separate deliberate action.');
      } else {
        // Frozen account exposure cannot be reduced by student input. Higher
        // declared exposure is conservatively retained and labelled assumed.
        const candidates=[a,b].filter(nonnegative);values[key]=invalidCaptured?null:candidates.length?Math.max(...candidates):null;
        if (a!=null && !nonnegative(a)) constraint('invalid-'+key,'Invalid exposure or loss assumption',`${key} is not a finite, nonnegative USD loss magnitude.`,
          'Negative risk/loss cannot create extra budget.','Supply a nonnegative dollar amount; unknown must remain blank.');
      }
      if (values[key]===null) unknown('missing-'+key,'risk','Risk assumption missing: '+key,
        'No usable declared or captured '+key+' value is available.',
        'Available exposure and configured paper budgets cannot be checked without this value.','Provide this paper assumption or retain an insufficient-information result.');
      provenance[key]={declared:finite(a)?a:null,captured:finite(b)?b:null,used:values[key],
        capturedInvalid:invalidCaptured,
        source:b!=null || invalidMarker?(text(account.source)||'Captured account value; source unspecified'):'Student-declared paper assumption',
        selection:isLimit?'Stricter nonnegative declared/captured limit; zero is exhausted':'Larger nonnegative declared/captured loss magnitude'};
    }
    result.metrics.riskAssumptions=values;
    result.metrics.riskProvenance=provenance;
    fact('risk-input-provenance','risk','Exposure and budget assumptions',
      Object.keys(values).map(key=>`${key}: ${values[key]===null?'unknown':usd(values[key])} (${provenance[key].source})`).join('; '),
      'Known captured exposure/loss is not reduced by student input; configured limits are not raised by a declaration. Uncaptured amounts remain student assumptions, not verified account facts.');
    if (!validSpec || !['entry','stop','target','quantity'].every(k=>positive(p[k])) || !nonnegative(p.cost)) {result.metrics.risk=null;return;}
    const distance=(p.entry-p.stop)*direction,rewardDistance=(p.target-p.entry)*direction;
    if (distance<=0 || rewardDistance<=0) {result.metrics.risk=null;return;}
    const grossLoss=distance*p.quantity*spec.valuePerPriceUnit,grossReward=rewardDistance*p.quantity*spec.valuePerPriceUnit;
    const plannedLoss=grossLoss+p.cost,netReward=grossReward-p.cost;
    const combinedRisk=values.openRisk===null?null:values.openRisk+plannedLoss;
    const dailyAtRisk=values.realizedLoss===null||combinedRisk===null?null:values.realizedLoss+combinedRisk;
    result.metrics.risk={distance,rewardDistance,quantity:p.quantity,valuePerPriceUnit:spec.valuePerPriceUnit,cost:p.cost,grossLoss,grossReward,
      plannedLoss,netReward,grossRewardRisk:grossReward/grossLoss,netRewardRisk:netReward/plannedLoss,combinedRisk,dailyAtRisk,currency:'USD',basis:spec.source};
    fact('risk-arithmetic','risk','Cost-inclusive planned arithmetic',
      `Loss at stop ${usd(plannedLoss)} = ${usd(grossLoss)} price-distance loss + ${usd(p.cost)} cost; net target reward ${usd(netReward)}; net reward/risk ${(netReward/plannedLoss).toFixed(2)}:1.`,
      'These are deterministic paper-plan calculations, not maximum possible losses or a probability of reaching either level.');
    if (netReward<=0) constraint('cost-reward','Costs consume the planned reward',
      `Gross target reward ${usd(grossReward)} minus cost ${usd(p.cost)} gives ${usd(netReward)}.`,
      'The plan has no positive net target reward under its own assumptions.','Reconsider the plan/cost evidence; do not treat a gross multiple as net reward.');
    for (const [id,value,limitKey,label] of [
      ['idea-budget',plannedLoss,'perIdeaLimit','Planned loss at stop'],
      ['combined-budget',combinedRisk,'combinedLimit','Open risk plus planned loss'],
      ['daily-budget',dailyAtRisk,'dailyLossLimit','Realized loss plus open risk and planned loss']
    ]) if (value!==null && values[limitKey]!==null && value>values[limitKey]+1e-8)
      constraint(id,'Declared/configured paper budget exceeded',`${label} ${usd(value)} exceeds ${limitKey} ${usd(values[limitKey])}.`,
        'This violates the available arithmetic budget for this paper plan. It is guidance here, not an execution lock.',
        'Reduce exposure/quantity or deliberately wait; retain an invalidation that still makes sense for the thesis.');
  }

  return {review,methodVersion,intervals,higherTimeframe,methods};
});
