// Shared presentation for Academy routes. Authentication and learning data stay server-owned.
const escapeText=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const titles={login:'Sign in',forgot:'Account recovery',enroll:'Join the Academy',account:'My account',classroom:'My classroom',start:'Guided introduction',classes:'Live classes',library:'Learning library',questions:'Questions & replies',contact:'Contact',privacy:'Privacy',terms:'Terms',risk:'Risk disclaimer',setup:'Instructor setup'};
const routeName=route=>titles[route.split('/')[0]]||(route.startsWith('lesson/')?'Your lesson':route.startsWith('reset/')?'Reset password':'Academy');
function closeNavigation(){
 const header=document.querySelector('body>header');
 header?.querySelector('nav')?.classList.remove('open');
 const toggle=header?.querySelector('.site-menu');
 toggle?.setAttribute('aria-expanded','false');toggle?.setAttribute('aria-label','Open navigation');
}
document.addEventListener('keydown',event=>{
 if(event.key==='Escape'&&document.querySelector('body>header nav.open')){
  closeNavigation();document.querySelector('.site-menu')?.focus();
 }
});
document.addEventListener('click',event=>{if(!event.target.closest('body>header'))closeNavigation()});
export function enhanceWorkspace(main,{route,user,canLearn,lessons,progress}){
 document.body.classList.add('academy-workspace');document.body.dataset.route=route.split('/')[0];
 const header=document.querySelector('body>header'),nav=header.querySelector('nav');
 header.querySelector('.brand').href='/';
 document.querySelector('footer .brand')?.setAttribute('href','/');
 header.querySelector('.site-menu').textContent='Menu';
  header.querySelector('.site-menu').setAttribute('aria-controls','academy-navigation');nav.id='academy-navigation';
  header.querySelector('.site-menu').setAttribute('aria-label','Open navigation');
  header.querySelector('.site-menu').onclick=()=>{
   const open=nav.classList.toggle('open'),toggle=header.querySelector('.site-menu');
   toggle.setAttribute('aria-expanded',String(open));toggle.setAttribute('aria-label',open?'Close navigation':'Open navigation');
  };
  nav.querySelectorAll('a').forEach(a=>{const hash=a.getAttribute('href');const active=hash==='#'+route||hash==='#classroom'&&(route.startsWith('lesson/')||route.startsWith('questions'));a.toggleAttribute('data-active',active);if(active)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current')});
  if(route==='classes'&&canLearn){
   const invitation=main.querySelector('.next-class + .panel');
   if(invitation)invitation.innerHTML='<h3>Bring a better question.</h3><p>Your classroom is ready. Keep your practice notes and ask about the step you want to understand before your next session.</p><a class="button secondary" href="#questions">Questions & replies <span aria-hidden="true">↗</span></a>';
  }
 if(document.body.classList.contains('teacher-mode'))return;
 const auth=main.querySelector('#auth-form,#reset-form,#verify-form');
 if(auth){
  const section=auth.closest('section');section.classList.add('auth-layout');section.classList.remove('narrow');
  const intro=document.createElement('div');intro.className='auth-intro';
  while(section.firstElementChild&&section.firstElementChild!==auth)intro.append(section.firstElementChild);
  const formSide=document.createElement('div');formSide.className='auth-side';
  while(section.firstChild)formSide.append(section.firstChild);
  if(auth.dataset.authMode==='login'){
   intro.querySelector('h1').innerHTML='Your next session.<br><em>A clearer perspective.</em>';
   intro.querySelector('p:not(.eyebrow)').textContent='Return to your lessons, saved practice and instructor conversations. One place to keep your learning moving.';
  }
  const visual=document.createElement('div');visual.className='auth-process';visual.innerHTML='<div class="process-rule"><span>UNDERSTAND</span><i></i><span>PLAN</span><i></i><span>REVIEW</span></div><svg viewBox="0 0 420 136" aria-hidden="true"><path class="auth-grid" d="M0 34H420M0 68H420M0 102H420M70 0V136M140 0V136M210 0V136M280 0V136M350 0V136"/><path class="auth-price" d="M0 112L24 96L48 105L75 76L103 86L129 62L157 73L183 45L208 59L238 29L261 41L289 20L320 35L347 13L376 25L403 9"/></svg><p>Build a process you can explain—and repeat.</p>';
  intro.append(visual);
  const formTitle=document.createElement('div');formTitle.className='auth-form-title';formTitle.innerHTML='<span class="eyebrow">YOUR ACADEMY ACCOUNT</span><h2>'+escapeText(auth.dataset.authMode==='login'?'Welcome back.':routeName(route))+'</h2>';
  formSide.prepend(formTitle);
  section.append(intro,formSide);
 }
 const gate=main.querySelector('.classroom-gate');
 if(gate){const pathway=document.createElement('div');pathway.className='gate-path';pathway.innerHTML='<span class="eyebrow">INSIDE YOUR CLASSROOM</span><ol><li><span>01</span><div><h3>A clear learning path</h3><p>Move through the foundations one session at a time.</p></div></li><li><span>02</span><div><h3>Practice you can return to</h3><p>Keep your own notes alongside each lesson.</p></div></li><li><span>03</span><div><h3>Guidance when you need it</h3><p>Bring a specific question back to your instructor.</p></div></li></ol>';gate.append(pathway)}
 const crumb=document.createElement('nav');crumb.className='workspace-breadcrumb';crumb.setAttribute('aria-label','Breadcrumb');crumb.innerHTML='<a href="/">Academy</a><span aria-hidden="true">/</span>'+(route.startsWith('lesson/')?'<a href="#classroom">My classroom</a><span aria-hidden="true">/</span>':'')+'<span aria-current="page">'+escapeText(routeName(route))+'</span>';
 main.prepend(crumb);
 if(canLearn&&['classroom','account','questions','lesson','library','classes','start'].includes(route.split('/')[0])){
  const frame=document.createElement('div');frame.className='learning-shell';
  const rail=document.createElement('aside');rail.className='learning-rail';rail.innerHTML='<div class="rail-identity"><span class="rail-avatar">'+escapeText(user.name.trim().slice(0,1).toUpperCase())+'</span><div><b>'+escapeText(user.name)+'</b><small>'+escapeText(user.role==='teacher'?'Instructor view':'Your learning space')+'</small></div></div><nav aria-label="Learning navigation">'+[['classroom','My classroom','01'],['library','Learning library','02'],['classes','Live classes','03'],['questions','Questions & replies','04'],['account','My account','05']].map(([key,label,n])=>'<a href="#'+key+'" '+(route.split('/')[0]===key||(key==='classroom'&&route.startsWith('lesson/'))?'aria-current="page"':'')+'><span>'+n+'</span>'+label+'</a>').join('')+'</nav><div class="rail-foot"><span class="eyebrow">YOUR NEXT STEP. CLEARER.</span><p>Understand.<br>Practise.<br>Return with a question.</p><a href="#start">Revisit the introduction ↗</a></div>';
  const content=document.createElement('div');content.className='learning-content';while(main.firstChild)content.append(main.firstChild);frame.append(rail,content);main.append(frame);
  // Preserve orientation when the mobile navigation becomes a horizontal rail.
  requestAnimationFrame(()=>{
   if(!rail.isConnected||!matchMedia('(max-width:760px)').matches)return;
   const menu=rail.querySelector('nav'),active=menu.querySelector('[aria-current="page"]');
   if(active){const item=active.getBoundingClientRect(),bounds=menu.getBoundingClientRect();menu.scrollLeft+=item.left-bounds.left-(bounds.width-item.width)/2}
  });
 }
 if(route.startsWith('lesson/')&&canLearn){
  const i=Number(route.split('/')[1]);const article=document.createElement('article');article.className='panel lesson-map';article.innerHTML='<span class="eyebrow">YOUR LEARNING PATH</span><nav aria-label="Lesson navigation">'+lessons.map((l,n)=>'<a href="#lesson/'+n+'" '+(n===i?'aria-current="step"':'')+'><span>'+String(n+1).padStart(2,'0')+'</span><b>'+escapeText(l.title)+'</b>'+(progress.some(p=>p.lesson===n&&p.complete)?'<small aria-label="Practised">✓</small>':'')+'</a>').join('')+'</nav>';
  main.querySelector('.dashboard>aside')?.prepend(article);
 }
}
