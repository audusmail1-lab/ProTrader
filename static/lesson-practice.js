/* A local educational exercise. No market requests, order submission or account writes. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else {
    root.LessonPractice = api;
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => api.mount(document));
    else api.mount(document);
  }
})(typeof window === 'undefined' ? globalThis : window, function () {
  'use strict';
  const KEY = 'protrader.lesson.explain-idea.v1';
  const STEPS = ['Learn', 'Observe', 'Decide', 'Review', 'Reflect'];
  // Only bars at or before the decision cutoff exist in these cases. There is no outcome reveal.
  const CASES = Object.freeze([
    {
      id: 'level-retest', title: 'A return to a level', cutoff: '12:00', level: 102,
      intro: 'A fictional market rose, pulled back, then returned above 102. Decide what the closed candles support before planning anything.',
      bars: [[100,101.5,99.5,101],[101,103,100.5,102.5],[102.5,104,102,103.5],[103.5,105,103,104.5],[104.5,106,104,105.5],[105.5,106,104.5,105],[105,105.5,103.5,104],[104,104.5,102,102.5],[102.5,103,101.5,102],[102,103,101.5,102.5],[102.5,104,102,103.5],[103.5,104.5,103,104]],
      evidence: [
        {id:'last', text:'The last closed candle closes at 104.', fact:true},
        {id:'level', text:'The pullback reached 101.5, below the 102 reference level.', fact:true},
        {id:'high', text:'The visible highest high is 106.', fact:true},
        {id:'prediction', text:'Price will definitely rise from here.', fact:false},
        {id:'probability', text:'Several agreeing checks prove the chance of a win.', fact:false}
      ]
    },
    {
      id: 'range-edge', title: 'A second level, less help', cutoff: '12:00', level: 106,
      intro: 'Use the same decision process on a different fictional case. Build your explanation without a worked trade plan.',
      bars: [[102,103,101.5,102.5],[102.5,104,102,103.5],[103.5,106,103,105.5],[105.5,106.5,104.5,105],[105,105.5,103,103.5],[103.5,104,102,102.5],[102.5,103.5,101.5,103],[103,104.5,102.5,104],[104,106,103.5,105.5],[105.5,106.5,105,106],[106,106.5,104.5,105],[105,105.5,104,104.5]],
      evidence: [
        {id:'last', text:'The last closed candle closes at 104.5.', fact:true},
        {id:'level', text:'Several visible candles traded at or above 106.', fact:true},
        {id:'low', text:'The visible lowest low is 101.5.', fact:true},
        {id:'prediction', text:'A repeated high guarantees a reversal.', fact:false},
        {id:'probability', text:'An indicator agreement count measures a win probability.', fact:false}
      ]
    }
  ].map(c => Object.freeze({...c, bars:Object.freeze(c.bars.map(b => Object.freeze(b))), evidence:Object.freeze(c.evidence.map(e => Object.freeze(e)))})));

  const blankAttempt = () => ({observation:'', idea:'', evidence:[], invalidation:'', invalidationPrice:'', action:'wait', waitReason:'', waitTrigger:'', waitPrice:'', side:'long', entry:'', stop:'', target:'', units:'', agreement:'', process:'', selfReview:false, reflection:'', nextAction:'', completedAt:null, review:null});
  const blankState = () => ({version:1, caseIndex:0, step:0, attempts:CASES.map(blankAttempt), updatedAt:null});
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const textOK = value => typeof value === 'string' && value.trim().length >= 15;
  const positive = value => value !== '' && Number.isFinite(Number(value)) && Number(value) > 0;

  function planMath(a) {
    if (![a.entry,a.stop,a.target,a.units].every(positive)) return null;
    const [entry,stop,target,units] = [a.entry,a.stop,a.target,a.units].map(Number);
    const sign = a.side === 'short' ? -1 : 1;
    const distance = sign * (entry - stop), rewardDistance = sign * (target - entry);
    return {entry,stop,target,units,distance,rewardDistance,risk:distance * units,reward:rewardDistance * units,ratio:rewardDistance / distance};
  }
  function reviewAttempt(a, caseIndex) {
    const c = CASES[caseIndex], selected = Array.isArray(a.evidence) ? a.evidence : [];
    const facts = selected.filter(id => c.evidence.find(e => e.id === id)?.fact);
    const hasPrediction = selected.some(id => !c.evidence.find(e => e.id === id)?.fact);
    const math = planMath(a);
    const invalidationSide = math && positive(a.invalidationPrice) && (a.side === 'short' ? Number(a.invalidationPrice) > math.entry : Number(a.invalidationPrice) < math.entry);
    const stopBeyond = invalidationSide && (a.side === 'short' ? math.stop >= Number(a.invalidationPrice) : math.stop <= Number(a.invalidationPrice));
    const checks = [
      {id:'evidence', ok:facts.length >= 2 && !hasPrediction, title:'Separate facts from forecasts', detail:facts.length >= 2 && !hasPrediction ? 'You selected at least two verifiable chart facts. A forecast is still an interpretation.' : 'Select at least two chart facts and remove predictions or probability claims from your evidence.'},
      {id:'explanation', ok:textOK(a.observation) && textOK(a.idea), title:'Write an observation and an interpretation', detail:'The form checks that both are present. Read them yourself: could someone verify the observation from these candles, and does the idea explain rather than promise?'},
      {id:'invalidation', ok:textOK(a.invalidation) && positive(a.invalidationPrice), title:'Name what would change your mind', detail:'Give a price and an observable condition. The form checks completeness; you must judge whether the level logically challenges your own idea.'},
      {id:'decision', ok:a.action === 'wait' ? textOK(a.waitReason) && textOK(a.waitTrigger) && positive(a.waitPrice) : a.action === 'plan' && !!math && Number.isInteger(math.units) && math.distance > 0 && math.rewardDistance > 0 && math.risk <= 50 && math.ratio >= 2 && !!stopBeyond,
        title:a.action === 'wait' ? 'Make waiting deliberate' : 'Keep the fictional paper plan within the class rule',
        detail:a.action === 'wait' ? 'Record a reason to wait, a specific observable revisit condition and its price. Waiting earns the same process credit as a sound plan.' : 'Use whole classroom units. The stop must be beyond your stated invalidation and on the loss side; the target must be on the reward side. Maximum planned loss is $50 and planned gross reward/risk is at least 2. These teaching rules are checked here only.'},
      {id:'agreement', ok:a.agreement === 'checks', title:'Read agreement honestly', detail:'8 of 10 means eight setup checks met. It does not establish an 80% chance of winning. The ARIA count describes checklist agreement. Oracle explores market evidence with you. Journal reviews a recorded paper hypothesis with context, logic, risk and evidence rules. Neither establishes win probability.'},
      {id:'process', ok:a.process === 'discipline', title:'Judge the process separately from one result', detail:'One losing outcome can follow a sound process. One profitable outcome does not repair a broken rule.'}
    ];
    return {checks, ready:checks.every(c => c.ok), math:a.action === 'plan' ? math : null};
  }
  function validateStep(a, step) {
    if (step === 1 && (!textOK(a.observation) || !textOK(a.idea) || a.evidence.length < 2 || !textOK(a.invalidation) || !positive(a.invalidationPrice))) return 'Add your observation, at least two evidence choices, your interpretation, and a price-based invalidation. Use at least 15 characters for each written explanation.';
    if (step === 2 && a.action === 'wait' && (!textOK(a.waitReason) || !textOK(a.waitTrigger) || !positive(a.waitPrice))) return 'Give a reason to wait, a concrete revisit condition (15 characters each), and a valid revisit price.';
    if (step === 2 && a.action === 'plan' && !planMath(a)) return 'Complete entry, stop, target and whole classroom units with positive numbers. The next step checks the arithmetic.';
    if (step === 3 && (!a.review?.ready || !a.selfReview)) return 'Resolve the listed checks and confirm you reviewed the meaning of your own explanation before reflecting.';
    if (step === 4 && (!textOK(a.reflection) || !textOK(a.nextAction))) return 'Write a reflection and one measurable next action, using at least 15 characters each.';
    return '';
  }

  function readState(storage) {
    try {
      const raw = storage.getItem(KEY);
      if (!raw) return {state:blankState(), warning:''};
      const parsed = JSON.parse(raw);
      if (parsed.version !== 1 || !Array.isArray(parsed.attempts) || parsed.attempts.length !== CASES.length || !Number.isInteger(parsed.caseIndex) || parsed.caseIndex < 0 || parsed.caseIndex >= CASES.length || !Number.isInteger(parsed.step) || parsed.step < 0 || parsed.step > 5) throw new Error('Invalid lesson record');
      const state = blankState();
      state.caseIndex = parsed.caseIndex; state.step = parsed.step; state.updatedAt = parsed.updatedAt;
      state.attempts = parsed.attempts.map(a => {
        if (!a || typeof a !== 'object') throw new Error('Invalid attempt');
        const clean = blankAttempt();
        for (const k of Object.keys(clean)) if (typeof clean[k] === 'string') clean[k] = typeof a[k] === 'string' ? a[k].slice(0,4000) : clean[k];
        clean.action = a.action === 'plan' ? 'plan' : 'wait'; clean.side = a.side === 'short' ? 'short' : 'long';
        clean.evidence = Array.isArray(a.evidence) ? [...new Set(a.evidence.filter(v => typeof v === 'string'))].slice(0,5) : [];
        clean.selfReview = a.selfReview === true;
        clean.completedAt = typeof a.completedAt === 'string' ? a.completedAt : null;
        return clean;
      });
      // Saved feedback is derived again instead of trusting stored pass flags.
      state.attempts.forEach((a,i) => { if (i === state.caseIndex && state.step >= 3 || a.completedAt) a.review = reviewAttempt(a,i); });
      if (state.caseIndex === 1 && !state.attempts[0].completedAt) { state.caseIndex=0; state.step=0; }
      if (state.step === 5 && !state.attempts[state.caseIndex].completedAt) state.step=4;
      return {state,warning:''};
    } catch (_) {
      return {state:blankState(),warning:'Saved lesson storage could not be read. This session can continue, but it is not being saved. Export your learning record before closing. Existing storage has been left untouched.'};
    }
  }
  function writeState(storage, state) {
    try { storage.setItem(KEY,JSON.stringify(state)); return ''; }
    catch (_) { return 'Your browser could not save this lesson. Keep this tab open and export your learning record before closing; a reload may lose these changes.'; }
  }
  function record(state) {
    return {title:'Explain your trade idea before acting', version:1, savedIn:persistenceLabel(), exportedAt:new Date().toISOString(), cases:CASES.map((c,i) => ({caseId:c.id,fictional:true,timeframe:'15m',lastClosedAt:c.cutoff,visibleBars:c.bars,attempt:state.attempts[i]})), progress:{caseIndex:state.caseIndex,step:state.step}, updatedAt:state.updatedAt,connections:{oracleStorageKey:'protrader.oracle.learning.v1',journalStorageKey:'protrader.oracle.learning.v1',purpose:'Apply this process to a current-market hypothesis in Journal. Account saving follows the workspace status.'}};
  }
  function chart(c) {
    const low = Math.min(...c.bars.map(b => b[2])) - .5, high = Math.max(...c.bars.map(b => b[1])) + .5;
    const y = p => 190 - (p-low)/(high-low)*158;
    const bars = c.bars.map((b,i) => { const x=43+i*39, cls=b[3]>=b[0]?'lp-up':'lp-down'; return `<g class="${cls}"><line x1="${x}" x2="${x}" y1="${y(b[1])}" y2="${y(b[2])}"/><rect x="${x-8}" y="${Math.min(y(b[0]),y(b[3]))}" width="16" height="${Math.max(1,Math.abs(y(b[0])-y(b[3])))}"/></g>`; }).join('');
    return `<div class="lp-chart-wrap"><svg class="lp-chart" viewBox="0 0 560 235" role="img" aria-label="Fictional 15 minute candlesticks, closed bars from 09:00 to 12:00. The table below contains every visible price."><line class="lp-level" x1="20" x2="510" y1="${y(c.level)}" y2="${y(c.level)}"/><text x="515" y="${y(c.level)+4}">${c.level}</text>${bars}<line class="lp-axis" x1="20" x2="510" y1="205" y2="205"/><text x="43" y="223" text-anchor="middle">09:15</text><text x="238" y="223" text-anchor="middle">10:30</text><text x="472" y="223" text-anchor="middle">12:00</text><text x="23" y="18">Fictional · 15m · all shown bars closed</text></svg><p class="lp-hint">Decision cutoff: 12:00, after the last bar closes. Blue reference: ${c.level}. There is no forming candle and no future price data in this exercise.</p><details><summary>Read the candle prices</summary><table class="lp-table"><thead><tr><th scope="col">Close time</th><th scope="col">Open</th><th scope="col">High</th><th scope="col">Low</th><th scope="col">Close</th></tr></thead><tbody>${c.bars.map((b,i) => {const mins=9*60+15+i*15;return `<tr><th scope="row">${String(Math.floor(mins/60)).padStart(2,'0')}:${String(mins%60).padStart(2,'0')}</th>${b.map(p=>`<td>${p}</td>`).join('')}</tr>`;}).join('')}</tbody></table></details></div>`;
  }

  let doc, dialog, state, warning='', storage, storageReadable=true, accountChanging=false;
  const current = () => state.attempts[state.caseIndex];
  function persistenceLabel(){try{return window.ProTraderStorageStatus?.()||'Saved in this browser on this site. No cloud sync; export a copy before clearing site data.';}catch(_){return'Saved in this browser on this site. No cloud sync; export a copy before clearing site data.';}}
  function save() {
    if(accountChanging)return;
    state.updatedAt=new Date().toISOString();
    if (storageReadable) warning=writeState(storage,state);
    const status=doc.getElementById('lpSave');
    if(status) {status.textContent=warning||persistenceLabel();status.classList.toggle('lp-warning',!!warning);}
    const button=doc.getElementById('lessonEntry');
    if(button) {button.textContent=state.attempts.every(a=>a.completedAt)?'Learn ✓':'Learn';button.title='Explain your trade idea before acting · paper practice';}
  }
  const area=(name,label,hint='')=>`<label class="lp-field" for="lp-${name}">${label}<textarea id="lp-${name}" data-field="${name}" maxlength="2000" rows="3">${esc(current()[name])}</textarea>${hint?`<span class="lp-hint">${hint}</span>`:''}</label>`;
  const number=(name,label,hint='')=>`<label class="lp-field" for="lp-${name}">${label}<input id="lp-${name}" type="number" inputmode="decimal" min="0" step="${name==='units'?'1':'any'}" data-field="${name}" value="${esc(current()[name])}"/>${hint?`<span class="lp-hint">${hint}</span>`:''}</label>`;
  const radio=(field,value,label)=>`<label class="lp-choice"><input type="radio" name="lp-${field}" data-field="${field}" value="${value}" ${current()[field]===value?'checked':''}/><span>${label}</span></label>`;
  function evidenceForm() {
    const c=CASES[state.caseIndex], guided=state.caseIndex===0;
    return `<h2 id="lpStepTitle">What can you see, and what might it mean?</h2><p>${esc(c.intro)}</p>${chart(c)}${guided?'<div class="lp-note"><strong>Observation:</strong> “The last candle closed above 102.” Someone can check that.<br/><strong>Interpretation:</strong> “Buyers may be defending the level.” That is an idea to test, not a promise.</div>':''}${area('observation','1. A chart observation',guided?'Describe a visible price or closed candle. Avoid “will” and “guaranteed”.':'Write a verifiable fact from the chart.')}<fieldset><legend>Choose at least two observations you can verify</legend>${c.evidence.map(e=>`<label class="lp-choice"><input type="checkbox" data-evidence="${e.id}" ${current().evidence.includes(e.id)?'checked':''}/><span>${e.text}</span></label>`).join('')}</fieldset>${area('idea','2. My interpretation and its evidence',guided?'Explain your possible direction or uncertainty, and connect it to the facts. Different interpretations can be reasonable.':'Connect your interpretation to your selected facts.')}${area('invalidation','3. What would change my mind?',guided?'Use an observable condition at a price, such as a closed candle below a level. A stop price alone is not an explanation.':'Describe the condition that would challenge your idea.')}${number('invalidationPrice','Invalidation reference price')}`;
  }
  function decisionForm() {
    const a=current(), guided=state.caseIndex===0;
    return `<h2 id="lpStepTitle">Choose a deliberate next step</h2><details class="lp-chart-wrap"><summary>Recheck the frozen chart</summary>${chart(CASES[state.caseIndex])}</details><p>This is a written paper exercise. Saving a plan creates a learning record; it does not open a position or change your trading account.</p><fieldset><legend>My decision</legend>${radio('action','wait','Wait — the evidence or conditions are not enough yet')}${radio('action','plan','Write a hypothetical paper plan')}</fieldset><div id="lpDecisionFields">${a.action==='wait'?`${area('waitReason','Why am I waiting?')}${area('waitTrigger','What exactly would make me look again?',guided?'Name a closed-candle or other observable condition. Rechecking is not an instruction to enter.':'State an observable condition.')}${number('waitPrice','Revisit reference price')}`:`<div class="lp-note"><strong>Fictional class rule:</strong> capital $10,000; maximum planned loss $50 (0.5%); one classroom unit earns or loses $1 per price point. Use whole units and at least 2:1 gross reward/risk. These are teaching assumptions, before costs, gaps or slippage; they are not broker contract sizes or your personal limits.</div><label class="lp-field" for="lp-side">Direction<select id="lp-side" data-field="side"><option value="long" ${a.side==='long'?'selected':''}>Long</option><option value="short" ${a.side==='short'?'selected':''}>Short</option></select></label><div class="lp-grid">${number('entry','Planned entry')}${number('stop','Planned stop')}${number('target','Planned target')}${number('units','Whole classroom units')}</div>${guided?'<p class="lp-hint">Arithmetic example only: entry 104, stop 101, target 110 and 16 units gives a $48 planned loss and $96 gross reward (2:1). Your own invalidation and evidence must justify your plan. Reduce units to fit the budget; do not tighten an invalidation stop just to fit it.</p>':''}<div class="lp-note" id="lpPlanMath">${mathText(a)}</div>`}</div>`;
  }
  function mathText(a) {
    const m=planMath(a);
    return m && m.distance>0 && m.rewardDistance>0 ? `Planned loss at stop: $${m.risk.toFixed(2)} · gross reward: $${m.reward.toFixed(2)} · reward/risk: ${m.ratio.toFixed(2)}:1. Estimated costs are not modelled here.` : 'Enter a stop on the loss side and a target on the reward side to see the calculation.';
  }
  function reviewForm() {
    const a=current(); a.review=reviewAttempt(a,state.caseIndex);
    return `<h2 id="lpStepTitle">Review your reasoning</h2><p>Guided self-review, using fixed rules. This checks selected chart facts, completeness, arithmetic and two concepts. It cannot judge the quality of your written thesis or predict a result.</p><fieldset><legend>If 8 of 10 setup checks agree, what do I know?</legend>${radio('agreement','checks','Eight checks met; the chance of winning has not been established.')}${radio('agreement','probability','There is an 80% chance this trade will win.')}</fieldset><fieldset><legend>A paper trade loses after I follow my written rules. How should I review it?</legend>${radio('process','discipline','Review the evidence and discipline separately from this single result.')}${radio('process','profit','A loss proves my decision process was wrong.')}</fieldset><div id="lpReviewChecks">${checksHTML(a.review)}</div><label class="lp-choice"><input type="checkbox" data-field="selfReview" ${a.selfReview?'checked':''}/><span>I re-read my explanation, challenged the evidence, and checked that the invalidation actually tests my idea. The form cannot establish that for me.</span></label>`;
  }
  function checksHTML(review) {
    return `<ul class="lp-checks">${review.checks.map(c=>`<li class="${c.ok?'':'lp-needs'}"><strong>${c.ok?'✓ Recorded':'↻ Revisit'} · ${esc(c.title)}</strong>${esc(c.detail)}</li>`).join('')}</ul>${review.math?`<div class="lp-note">${mathText(current())}</div>`:''}<p class="lp-muted">${review.ready?'The listed checks are met. Your explanation still needs your judgment.':'Revisit the highlighted checks. Use Back to edit observation or plan fields; answer the two concept questions here.'}</p>`;
  }
  function reflectForm() {
    return `<h2 id="lpStepTitle">Record what you learned</h2><p>No trade outcome is shown or scored. This exercise judges whether you explained a decision before acting.</p>${area('reflection','What did I learn about my reasoning?',state.caseIndex===0?'Name one strength or mistake in how you separated facts, interpretation and uncertainty.':'Compare this attempt with the guided example. What did you do with less help?')}${area('nextAction','One measurable action for my next practice',state.caseIndex===0?'For example: “Before my next three paper ideas, write one condition that would invalidate each.”':'Make the next action observable and repeatable.')}<div class="lp-note">Your reflection joins this lesson’s learning record. It is separate from the terminal’s closed-trade Journal and does not create a trade.</div>`;
  }
  function completed() {
    const a=current(), done=state.attempts.every(v=>v.completedAt);
    return `<h2 id="lpStepTitle">${done?'Two practice records completed':'Your first learning record is complete'}</h2><p>${done?'You repeated the process with less help. Keep testing your explanations on paper; these exercises do not establish a trading edge or readiness for real money.':'Next, try a similar fictional case with fewer prompts and no worked plan. You can close this lesson now and return later.'}</p><div class="lp-record"><div class="lp-eyebrow">${esc(CASES[state.caseIndex].title)} · ${a.action==='wait'?'Deliberate wait':'Hypothetical paper plan'}</div><p><strong>Your idea</strong></p><blockquote>${esc(a.idea)}</blockquote><p><strong>Reflection</strong></p><blockquote>${esc(a.reflection)}</blockquote><p><strong>Next practice action</strong></p><blockquote>${esc(a.nextAction)}</blockquote></div><p class="lp-muted">${warning?'Export is available even when browser storage fails.':esc(persistenceLabel())+' Export a copy to keep outside the browser.'}</p>${done?'<div class="lp-actions"><button data-action="showFirst">View first record</button><button data-action="showSecond">View second record</button></div>':''}`;
  }
  function render() {
    const c=CASES[state.caseIndex];
    let content='';
    if(state.step===0) content=`<h2 id="lpStepTitle">Explain your trade idea before acting</h2><p>Practise making a decision you can explain. Start with facts, develop an idea, name what would invalidate it, and choose a sensible paper plan or a deliberate wait.</p><div class="lp-note"><strong>About 8–12 minutes · ${state.caseIndex===0?'guided example':'second example with reduced help'}</strong><br/>Frozen fictional candles, with no future bars or outcome reveal. The active market chart behind this lesson is separate and is not used to mark your answers.</div><ul><li>Observation describes what happened. Interpretation explains what it might mean.</li><li>Setup-check agreement is not a measured win probability.</li><li>A well-reasoned wait is a valid decision. One profit or loss does not grade your process.</li></ul><p class="lp-muted">This is transparent self-review, not an AI tutor. ${esc(persistenceLabel())} Reopen Learn to resume. Export a copy when you finish.</p>`;
    else if(state.step===1)content=evidenceForm();
    else if(state.step===2)content=decisionForm();
    else if(state.step===3)content=reviewForm();
    else if(state.step===4)content=reflectForm();
    else content=completed();
    doc.getElementById('lessonPracticeContent').innerHTML=`<div class="lp-head"><div><div class="lp-eyebrow">Paper practice · Lesson 1</div><strong>${esc(c.title)}</strong></div><button type="button" data-action="close" aria-label="Close lesson">×</button></div><div class="lp-body"><ol class="lp-progress" aria-label="Lesson progress">${STEPS.map((s,i)=>`<li ${state.step===i?'aria-current="step"':''}>${i+1}. ${s}</li>`).join('')}</ol>${content}<p id="lpError" class="lp-error" role="alert"></p><div class="lp-actions">${state.step>0&&state.step<5?'<button data-action="back">Back</button>':''}${state.step<5?`<button class="lp-primary" data-action="next">${state.step===0?'Start '+(state.caseIndex===0?'guided case':'second case'):state.step===4?'Complete learning record':state.step===2?'Review my decision':'Continue'}</button>`:state.attempts[1].completedAt?'':'<button class="lp-primary" data-action="second">Try a similar case with less help</button>'}<button data-action="export" class="lp-small">Export learning record</button>${state.step===5?'<button data-action="oracle">Apply this process in Journal</button>':''}</div></div><div id="lpSave" class="lp-save" role="status" aria-live="polite"></div>`;
    save();
    dialog.scrollTop=0;
    const heading=doc.getElementById('lpStepTitle');heading.tabIndex=-1;heading.focus({preventScroll:true});
  }
  function handleChange(event) {
    if(accountChanging)return;
    const el=event.target, a=current();
    if(el.dataset.evidence) {a.evidence=Array.from(dialog.querySelectorAll('[data-evidence]:checked')).map(v=>v.dataset.evidence);a.selfReview=false;}
    else if(el.dataset.field) {a[el.dataset.field]=el.type==='checkbox'?el.checked:el.value;if(!['reflection','nextAction','selfReview'].includes(el.dataset.field))a.selfReview=false;}
    else return;
    if(state.step===3) {a.review=reviewAttempt(a,state.caseIndex);doc.getElementById('lpReviewChecks').innerHTML=checksHTML(a.review);const check=dialog.querySelector('[data-field="selfReview"]');if(check)check.checked=a.selfReview;}
    if(el.dataset.field==='action') {render();const input=dialog.querySelector('#lpDecisionFields textarea, #lpDecisionFields select');input?.focus();}
    else {const maths=doc.getElementById('lpPlanMath');if(maths)maths.textContent=mathText(a);save();}
  }
  function next() {
    const a=current();
    if(state.step===3)a.review=reviewAttempt(a,state.caseIndex);
    const error=validateStep(a,state.step);
    if(error){const node=doc.getElementById('lpError');node.textContent=error;node.scrollIntoView({block:'nearest'});return;}
    if(state.step===4) a.completedAt=new Date().toISOString();
    state.step++;render();
  }
  function download() {
    const blob=new Blob([JSON.stringify(record(state),null,2)],{type:'application/json'}), url=URL.createObjectURL(blob), a=doc.createElement('a');
    a.href=url;a.download='protrader-lesson-explain-your-idea.json';doc.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  function mount(documentRef) {
    if(doc)return;
    doc=documentRef;dialog=doc.getElementById('lessonPracticeDialog');if(!dialog)return;
    try{storage=window.localStorage;}catch(_){storage=null;}
    const loaded=readState(storage);state=loaded.state;warning=loaded.warning;storageReadable=!warning;
    dialog.addEventListener('input',handleChange);
    dialog.addEventListener('change',event=>{if(['checkbox','radio'].includes(event.target.type)||event.target.tagName==='SELECT')handleChange(event);});
    // Keep terminal shortcuts (including B/S/Delete) from changing the workspace beneath the lesson.
    dialog.addEventListener('keydown',event=>event.stopPropagation());
    dialog.addEventListener('click',event=>{
      if(accountChanging)return;
      const action=event.target.closest('[data-action]')?.dataset.action;
      if(action==='close')dialog.close();
      else if(action==='next')next();
      else if(action==='back'){state.step--;render();}
      else if(action==='second'&&state.attempts[0].completedAt){state.caseIndex=1;state.step=0;render();}
      else if(action==='export')download();
      else if(action==='oracle'){dialog.close();if(typeof window.openOracleLearning==='function')window.openOracleLearning({key:KEY,title:'Explain your trade idea before acting',completedCases:state.attempts.filter(a=>a.completedAt).length,updatedAt:state.updatedAt});}
      else if(action==='showFirst'||action==='showSecond'){state.caseIndex=action==='showFirst'?0:1;state.step=5;render();}
    });
    save();
  }
  function open() {
    if(!dialog||accountChanging)return;
    if(!dialog.open)dialog.showModal();
    render();
  }
  function clearForAccountChange(){
    accountChanging=true;dialog?.close();
    // Keep the content host so the incoming account can reopen Learn.
    const content=doc?.getElementById('lessonPracticeContent');if(content)content.innerHTML='';
    state=blankState();warning='Changing account…';storageReadable=false;
    const button=doc?.getElementById('lessonEntry');if(button)button.textContent='Learn';
  }
  function reloadStorage(){
    clearForAccountChange();try{storage=window.localStorage;}catch(_){storage=null;}
    const loaded=readState(storage);state=loaded.state;warning=loaded.warning;storageReadable=!warning;accountChanging=false;
    const button=doc?.getElementById('lessonEntry');if(button)button.textContent=state.attempts.every(a=>a.completedAt)?'Learn ✓':'Learn';
  }
  return {mount,open,clearForAccountChange,reloadStorage,KEY,CASES,blankState,blankAttempt,planMath,reviewAttempt,validateStep,readState,writeState,record,getState:()=>state?JSON.parse(JSON.stringify(state)):null};
});
