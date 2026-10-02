const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const money=n=>n.toLocaleString('en-US',{style:'currency',currency:'USD'});
let toastTimer;function toast(t){$('#toast').textContent=t;$('#toast').style.display='block';clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').style.display='none',3200)}
function showPage(){location.href='https://app.protraderacademy.company'}
const modal=$('#modal');function openModal(title,body,kicker='PRO TRADER ACADEMY'){$('#modal-title').textContent=title;$('#modal-body').innerHTML=body;$('#modal-kicker').textContent=kicker;modal.showModal();modal.scrollTop=0;$('#close-modal').focus()}$('#close-modal').onclick=()=>modal.close();modal.addEventListener('click',e=>{if(e.target===modal){const r=modal.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)modal.close()}});

$$('[data-page]').forEach(b=>b.onclick=showPage);
$$('[data-open]').forEach(b=>b.onclick=()=>location.href='/classroom#'+(b.dataset.open==='classroom'?'classroom':'privacy'));
// One Alex experience across the public site and classroom.
const alexSupportReady=import('./cinematic/alex-support.js?v=20261002-controls').then(({initAlexSupport})=>initAlexSupport());
function openAlexSupport(mode='text'){return alexSupportReady.then(support=>support.open(mode))}
function openAlexVoice(){return openAlexSupport('voice')}

// Keep existing bookmarks, verification and password-recovery links working.
function routeLegacyLink(){const route=location.hash.slice(1);if(route==='library'){location.replace('/#learn');return}if(route&&!['home','academy','intelligence','learn','path','workspace','risk','questions','journey','classroom-path','review','main-content'].includes(route))location.replace('/classroom'+location.hash)}
routeLegacyLink();window.addEventListener('hashchange',routeLegacyLink);
fetch('/api/session').then(r=>r.ok?r.json():null).then(data=>{if(data?.user){$('#account-link').textContent='My account';$('#account-link').href='/classroom#account'}}).catch(()=>{});
