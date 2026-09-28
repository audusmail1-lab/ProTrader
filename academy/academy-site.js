const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const money=n=>n.toLocaleString('en-US',{style:'currency',currency:'USD'});
let toastTimer;function toast(t){$('#toast').textContent=t;$('#toast').style.display='block';clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').style.display='none',3200)}
function showPage(){location.href='https://app.protraderacademy.company'}
const modal=$('#modal');function openModal(title,body,kicker='PRO TRADER ACADEMY'){$('#modal-title').textContent=title;$('#modal-body').innerHTML=body;$('#modal-kicker').textContent=kicker;modal.showModal();modal.scrollTop=0;$('#close-modal').focus()}$('#close-modal').onclick=()=>modal.close();modal.addEventListener('click',e=>{if(e.target===modal){const r=modal.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)modal.close()}});

$$('[data-page]').forEach(b=>b.onclick=showPage);
$$('[data-open]').forEach(b=>b.onclick=()=>location.href='/classroom#'+(b.dataset.open==='classroom'?'classroom':'privacy'));
$('#alex').onclick=()=>openAlexSupport('text');
let alexScriptPromise;
function loadAlexWidget(){
  if(customElements.get('elevenlabs-convai'))return Promise.resolve();
  if(alexScriptPromise)return alexScriptPromise;
  alexScriptPromise=new Promise((resolve,reject)=>{
    const script=document.createElement('script');
    script.src='https://unpkg.com/@elevenlabs/convai-widget-embed';script.async=true;
    const timeout=setTimeout(()=>{script.remove();alexScriptPromise=null;reject(new Error('Voice widget loading timed out.'));},20000);
    script.onload=()=>customElements.whenDefined('elevenlabs-convai').then(()=>{clearTimeout(timeout);resolve()});
    script.onerror=()=>{clearTimeout(timeout);script.remove();alexScriptPromise=null;reject(new Error('Voice widget could not load.'));};
    document.head.appendChild(script);
  });return alexScriptPromise;
}
async function openAlexSupport(mode='text'){
 if($('#academy').hidden)return;
 let host=$('#alex-voice-host');
 if(host){host.remove();}
 host=document.createElement('section');host.id='alex-voice-host';host.setAttribute('aria-label','Alex support');
 host.innerHTML='<div class="alex-support-bar"><div><b>Ask Alex</b><small><a href="#intelligence">Tool guides</a> · <a href="#learn">Lessons</a> · <a href="/classroom#contact">Academy team</a></small></div><button id="alex-mode"></button><button id="alex-close" aria-label="Close Alex support">×</button></div><p class="alex-status" role="status">Connecting Alex…</p>';
 $('#academy').append(host);$('#alex').hidden=true;host.querySelector('#alex-close').focus();host.querySelectorAll('a').forEach(link=>link.onclick=()=>{host.remove();$('#alex').hidden=false});
 const toggle=host.querySelector('#alex-mode');toggle.textContent=mode==='text'?'Call Alex':'Text Alex';toggle.disabled=true;
 toggle.onclick=()=>{if(host.dataset.conversationStarted!=='true'){openAlexSupport(mode==='text'?'voice':'text');return}if(host.querySelector('elevenlabs-convai')){openModal('Switch conversation mode?','<p>Switching ends the current conversation and opens a new '+(mode==='text'?'voice':'text')+' session.</p><button class="dark-button" id="confirm-alex-mode">Switch to '+(mode==='text'?'calling':'text')+'</button>','ASK ALEX');$('#confirm-alex-mode').onclick=()=>{modal.close();openAlexSupport(mode==='text'?'voice':'text')}}};
 host.querySelector('#alex-close').onclick=()=>{host.remove();$('#alex').hidden=false;$('#alex').focus()};
 try{
  await loadAlexWidget();if(!host.isConnected||$('#academy').hidden)return;
  const widget=document.createElement('elevenlabs-convai');
  try {
   const response=await fetch('https://api.elevenlabs.io/v1/convai/agents/agent_4801m3by5dhceh5rwx83ynt33ra3/widget',{signal:AbortSignal.timeout(10000)});
   if(response.ok){const {widget_config:config}=await response.json();
    config.first_message='Hi, I’m Alex. Ask me about the Academy, ARIA, Oracle, Sentinel or finding your next lesson.';
    config.styles={...config.styles,base:'#151f16',base_primary:'#edf3e7',base_subtle:'#acbaa2',base_border:'#3b4d32',accent:'#cce6ab',accent_primary:'#152115',overlay_padding:16,button_radius:10,input_radius:10,sheet_radius:14};
    widget.setAttribute('override-config',JSON.stringify(config));
   }
  }catch(e){/* The widget can still fetch its standard configuration. */}
  if(!host.isConnected)return;
  const attrs={'agent-id':'agent_4801m3by5dhceh5rwx83ynt33ra3','variant':'full','default-expanded':'true','always-expanded':'true','dismissible':'false','override-text-only':String(mode==='text'),'text-input':'true','transcript':'true','show-avatar-when-collapsed':'false','show-conversation-id':'false','show-resize-button':'false','markdown-link-allowed-hosts':'protraderacademy.company,app.protraderacademy.company','markdown-link-allow-http':'false'};
  Object.entries(attrs).forEach(([k,v])=>widget.setAttribute(k,v));
  widget.setAttribute('text-contents',JSON.stringify({main_label:'Ask Alex',start_call:'Call Alex',start_chat:'Chat with Alex',input_placeholder_text_only:'Ask about the Academy or product…',input_placeholder_new_conversation:'Ask about the Academy or product…'}));
  widget.setAttribute('allow-events','true');
  widget.addEventListener('elevenlabs-convai:call',event=>{
    event.detail.config.onConnect=()=>{host.dataset.conversationStarted='true';setTimeout(()=>widget.dispatchEvent(new CustomEvent('elevenlabs-agent:contextual-update',{detail:{message:ALEX_PRODUCT_CONTEXT}})),0)};
  });
  host.append(widget);toggle.disabled=false;host.querySelector('.alex-support-bar').append(host.querySelector('.alex-status'));host.querySelector('.alex-status').textContent=mode==='text'?'Text chat with Alex · Messages go to ElevenLabs.':'Choose Call Alex below to begin. Microphone access starts with your call.';
 }catch(e){if(host.isConnected){host.querySelector('.alex-status').textContent='Alex could not connect. Please try again, or explore the written guides.';const retry=document.createElement('button');retry.className='dark-button';retry.textContent='Retry Alex';retry.onclick=()=>openAlexSupport(mode);host.append(retry)}}
}
function openAlexVoice(){return openAlexSupport('voice')}

// Public product facts only. No account, portfolio or market data is shared.
const ALEX_PRODUCT_CONTEXT = `Authoritative Pro Trader Academy website support context, updated 28 September 2026. Explain the Academy and product using these facts and correct conflicting older descriptions. ARIA evaluates ten defined market conditions for the selected market and timeframe, showing passed and failed checks. Oracle summarizes the SAME checks: eight of ten = 80% agreement, not win probability and not independent confirmation. Sentinel is a server-side research monitoring system across configured markets AND timeframes 24/7 even with the browser closed. It checks newly closed candles and closed four-hour trend alignment and tracks qualifying paper setups and outcomes by model version. Scans run sequentially in each cycle; feeds and market hours affect updates. Sentinel does NOT see or manage visitors' real positions and does NOT execute broker orders. Live operational Sentinel reads belong in the app Analysis area, not this website chat. You cannot see a visitor's trades, account, private journal or live markets. Do not invent those capabilities or guarantee returns. Website: https://protraderacademy.company ; product workspace: https://app.protraderacademy.company . Website lessons explain charts, order planning, risk, scanner, journal, ARIA and Oracle. Written explanations remain primary; videos are optional in a collapsible library, narrated by Callan. For written Sentinel explanations link to https://protraderacademy.company/#intelligence (Our tools). For ARIA and Oracle explanations use Our tools too. For lessons and optional videos link to https://protraderacademy.company/#learn (Learning library). Do not claim a dedicated Sentinel video or course lesson exists. Academy and app sign-ins are separate. Ask what screen the visitor is on when diagnosing access. Risk budgeting depends on size and stop distance; fees and slippage can increase loss. Do not recommend specific trades. For uncertain prices, account issues, enrollment terms, features or contact details say you cannot verify and direct the visitor to the Academy's published support or classroom. Visitors can message the Academy team via /classroom#contact. Do not claim to send a ticket yourself. This is the Academy education website. Its example chart is illustrative; actual market and account reads belong in the separate trading app. Keep answers brief, specific and helpful. Never show speech-direction tags such as [warmly] in text.`;

// Keep existing bookmarks, verification and password-recovery links working.
function routeLegacyLink(){const route=location.hash.slice(1);if(route==='library'){location.replace('/#learn');return}if(route&&!['home','academy','intelligence','learn','path','workspace','risk','questions','main-content'].includes(route))location.replace('/classroom'+location.hash)}
routeLegacyLink();window.addEventListener('hashchange',routeLegacyLink);
fetch('/api/session').then(r=>r.ok?r.json():null).then(data=>{if(data?.user){$('#account-link').textContent='My account';$('#account-link').href='/classroom#account'}}).catch(()=>{});
