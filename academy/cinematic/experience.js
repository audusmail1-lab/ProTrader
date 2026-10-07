/* Academy cinematic preview. Deterministic educational examples, no market feed. */
(() => {
  'use strict';
  const $ = s => document.querySelector(s);
  const $$ = s => [...document.querySelectorAll(s)];
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  let sceneFailed=false;
  const stillRequested=new URLSearchParams(location.search).get('motion')==='still';
  const staticMode=()=>reduced.matches||stillRequested||Boolean(navigator.connection?.saveData)||sceneFailed;
  const chapters = [
    {label:'Arrive',kicker:'PRO TRADER ACADEMY',title:'Understand the chart.<br><em>Build your process.</em>',body:'A clearer view of the market. A stronger reason for your next move. Bring ARIA’s reasoning, Oracle’s agreement and Sentinel’s monitoring into one deliberate process.',note:'A clearer way to learn trading.'},
    {label:'Understand',kicker:'01 / FIND THE STRUCTURE',title:'Look beyond<br><em>the next candle.</em>',body:'Find the levels. Read the structure. Put a single move in the context of the market around it.',note:'Price. Structure. Perspective.'},
    {label:'Interpret',kicker:'02 / CONNECT THE EVIDENCE',title:'Three perspectives.<br><em>One clear process.</em>',body:'ARIA explains. Oracle summarises. Sentinel monitors across markets and timeframes. Learn the role—and the limits—of each.',note:'Evidence supports a decision. It does not make it certain.'},
    {label:'Plan',kicker:'03 / MAKE RISK MEASURABLE',title:'Every adjustment<br><em>changes the plan.</em>',body:'Connect entry, stop and target. Read how each level changes estimated risk and reward, with position size kept in view.',note:'Paper practice. Measurable consequences.'},
    {label:'Review',kicker:'04 / BUILD THE ROUTINE',title:'Keep the reasoning.<br><em>Improve the process.</em>',body:'Return to the plan. Record what you saw, what you did and what you learned. Bring a better question to the next session.',note:'Understand. Plan. Practise. Review.'}
  ];
  const journey = document.createElement('section');
  journey.id='journey';journey.className='cinematic-journey';journey.setAttribute('aria-label','The Academy learning journey');
  journey.innerHTML=`<div class="journey-stage"><div class="journey-ambient" aria-hidden="true"></div><div class="scene-wrap" aria-hidden="true"><div id="workspace-scene" class="workspace-display"></div></div><div class="journey-scrim" aria-hidden="true"></div><div class="journey-copy">${chapters.map((s,i)=>`<div class="journey-chapter ${i===0?'active':''}" data-chapter="${i}" ${i?'hidden':''}><span class="eyebrow"><i></i>${s.kicker}</span>${i===0?`<h1>${s.title}</h1>`:`<h2>${s.title}</h2>`}<p>${s.body}</p></div>`).join('')}<div class="journey-actions"><a class="dark-button" href="/classroom#start">Start learning</a><a class="outline-button" href="#classroom-path">Explore the classroom</a></div><div class="journey-caption" id="journey-caption">${chapters[0].note}</div></div><div class="scene-tag"><span class="precision-dot"></span> PROTRADER / ILLUSTRATIVE WORKSPACE</div><div class="journey-navigation"><div class="journey-progress" aria-hidden="true"><i></i></div><div class="journey-nav-row"><div class="chapter-links" role="group" aria-label="Journey chapters">${chapters.map((c,i)=>`<button data-jump="${i}" aria-label="Show ${c.label.toLowerCase()} chapter" ${i===0?'aria-current="step"':''}><span>0${i+1}</span><b>${c.label}</b></button>`).join('')}</div><div class="journey-utilities"><button id="journey-motion" aria-pressed="false" aria-label="Pause cinematic motion"><svg class="academy-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><use href="/ui-icons.svg#pause"></use></svg></button><a href="#intelligence">Skip to tools</a></div></div></div></div>`;
  $('.hero').replaceWith(journey);
  const initialScreen=$('#workspace-preview-template');
  if(initialScreen)$('#workspace-scene').append(initialScreen.content.cloneNode(true));
  $('.site-header .logo').href='#journey';
  $('.footer-brand').href='#journey';
  // All text and destinations are available before the optional 3D runtime loads.
  let current=0,progress=0,queued=false,manual=false;
  const short = () => matchMedia('(max-width:700px)').matches;
  function paused(){return staticMode()||document.documentElement.classList.contains('motion-paused')}
  function setChapter(i){
    if(i===current)return;
    current=i;
    $$('.journey-chapter').forEach((el,n)=>{el.hidden=n!==i;el.classList.toggle('active',n===i)});
    $$('[data-jump]').forEach((el,n)=>n===i?el.setAttribute('aria-current','step'):el.removeAttribute('aria-current'));
    $('#journey-caption').textContent=chapters[i].note;
  }
  function update(){
    queued=false;
    const rect=journey.getBoundingClientRect();
    const travel=Math.max(1,journey.offsetHeight-innerHeight);
    if(!staticMode()){progress=Math.min(1,Math.max(0,-rect.top/travel));setChapter(Math.min(4,Math.floor(progress*5)))}
    journey.style.setProperty('--journey-progress',progress);
    journey.dataset.chapter=String(current);
    document.dispatchEvent(new CustomEvent('academy:journey',{detail:{progress,paused:paused(),static:staticMode(),active:rect.bottom>0&&rect.top<innerHeight,mobile:short()}}));
  }
  const queue=()=>{if(!queued){queued=true;requestAnimationFrame(update)}};
  addEventListener('scroll',queue,{passive:true});addEventListener('resize',queue,{passive:true});
  $$('[data-jump]').forEach(b=>b.onclick=()=>{
    const index=Number(b.dataset.jump);
    if(staticMode()){progress=(index+.15)/5;setChapter(index);scrollTo({top:scrollY+journey.getBoundingClientRect().top,behavior:'instant'});update();return}
    const top=scrollY+journey.getBoundingClientRect().top;
    scrollTo({top:top+(journey.offsetHeight-innerHeight)*(index+.15)/5,behavior:'smooth'});
  });
  function syncMotion(){
    const off=paused();journey.classList.toggle('is-static',staticMode());
    const b=$('#journey-motion');b.disabled=staticMode();b.setAttribute('aria-pressed',String(off));b.setAttribute('aria-label',staticMode()?'Still view enabled':off?'Enable cinematic motion':'Pause cinematic motion');b.innerHTML=`<svg class="academy-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><use href="/ui-icons.svg#${off?'play':'pause'}"></use></svg>`;
    queue();
  }
  $('#journey-motion').onclick=()=>{
    manual=!paused();
    document.documentElement.classList.toggle('motion-paused',manual);
    const footer=$('.motion-toggle');if(footer){footer.textContent=manual?'Enable motion':'Pause motion';footer.setAttribute('aria-pressed',String(manual))}
  };
  new MutationObserver(syncMotion).observe(document.documentElement,{attributes:true,attributeFilter:['class']});
  reduced.addEventListener('change',syncMotion);syncMotion();

  // Frame the existing, fully functional intelligence experience as one system.
  $('#intelligence .intelligence-heading').innerHTML='<div><span class="eyebrow">THE INTELLIGENCE BEHIND YOUR WORKSPACE</span><h2>Meet the intelligence.<br><em>Learn its language.</em></h2></div><p>ARIA explains. Oracle summarises.<br>Sentinel keeps the wider view.<span class="quiet">Explore how the tools connect, one example at a time.</span></p>';
  const bridge=document.createElement('div');bridge.className='journey-bridge';bridge.innerHTML='<span>FROM OBSERVATION TO UNDERSTANDING</span><i aria-hidden="true"></i><p>The tools bring structure.<br><b>You bring the judgement.</b></p>';
  journey.after(bridge);
  // Ground the cinematic introduction in a real, visible classroom route.
  const classroom=document.createElement('section');classroom.id='classroom-path';classroom.className='classroom-path reveal is-visible';
  classroom.innerHTML='<div class="classroom-copy"><span class="eyebrow">03 / THE ACADEMY MAKES IT PRACTICAL</span><h2>Build understanding.<br><em>Then build your process.</em></h2><p>The workspace gives you tools. The Academy helps you use them with intention.</p><a class="dark-button" href="/classroom#start">Start the guided introduction</a><a class="text-button" href="/classroom#classes">Explore scheduled classes</a></div><div class="classroom-board"><div class="board-top"><span class="precision-dot"></span> YOUR LEARNING PATH <span>ACADEMY</span></div><div class="classroom-feature"><span class="lesson-number">01</span><div><small>START WITH UNDERSTANDING</small><h3>Understand one thing well.</h3><p>Read a clear explanation.<br>Watch a short lesson when you want a demonstration.</p></div><button id="classroom-chart" aria-label="Open chart essentials guide">Read guide</button></div><button class="path-row" data-c-guide="0"><span>02</span><div><b>Put the idea on a chart.</b><small>Define entry, stop, size and target.</small></div></button><button class="path-row" data-c-guide="3"><span>03</span><div><b>Keep the reasoning.</b><small>Record the decision as well as the result.</small></div></button><div class="classroom-foot">Written guides · Short films · Instructor support</div></div>';
  $('#path').before(classroom);
  $('#classroom-chart').onclick=()=>document.dispatchEvent(new CustomEvent('academy:guide',{detail:1}));
  $$('[data-c-guide]').forEach(b=>b.onclick=()=>document.dispatchEvent(new CustomEvent('academy:guide',{detail:+b.dataset.cGuide})));
  $('#path').remove();
  const review=document.createElement('section');review.id='review';review.className='review-section';review.innerHTML='<div class="review-paper"><div class="paper-heading"><span>PROCESS JOURNAL</span><span>EXAMPLE ENTRY / 001</span></div><div class="paper-row"><span>THE CONTEXT</span><p>Structure first.<br>The conditions behind the idea.</p></div><div class="paper-row"><span>THE PLAN</span><p>Define the invalidation.<br>Size the position to the risk.</p></div><div class="paper-row"><span>THE REVIEW</span><p>What followed the plan?<br>What deserves another look?</p></div><div class="paper-signoff"><i></i> A record of reasoning. A starting point for improvement.</div></div><div class="review-copy"><span class="eyebrow">04 / REVIEW. REFINE. REPEAT.</span><h2>A result is one moment.<br><em>A process is something you build.</em></h2><p>Keep the context behind each decision. Review paper outcomes with your original plan, then turn the lesson into something you can use next time.</p><button class="outline-button" id="review-guide">Learn how to review a trade</button></div>';
  $('#learn').before(review);$('#review-guide').onclick=()=>document.dispatchEvent(new CustomEvent('academy:guide',{detail:3}));
  $('.closing h2').innerHTML='Make your next step<br><em>a deliberate one.</em>';
  $('.closing-actions').innerHTML='<a class="dark-button" href="/classroom#start">Start learning</a><a class="outline-button" href="https://app.protraderacademy.company/">Open the paper workspace</a><span>Educational tools. No guaranteed outcomes.</span>';
  // Static/reduced-motion visitors receive the same readable product visual.
  import('./scene.js?v=20261007-safari1').then(m=>m.mountScene($('#workspace-scene'),queue,{staticView:staticMode()})).catch(()=>{sceneFailed=true;syncMotion()});
  import('./product-refinement.js?v=20261007-safari1').then(m=>m.refineProduct());
  update();
})();
