import {ALEX_PRODUCT_CONTEXT} from './alex-context.js?v=20261007-safari1';

const AGENT_ID='agent_4801m3by5dhceh5rwx83ynt33ra3';
// Pin the embed because our compact layout adapter targets this tested release.
const WIDGET_URL='/cinematic/elevenlabs-widget-0.18.3.js';
const SETTINGS_KEY='academy-alex-public-settings-v1';
const SAMPLERATE_URL='https://cdn.jsdelivr.net/npm/@alexanderolsen/libsamplerate-js@2.1.2/dist/libsamplerate.worklet.js';
let widgetScript,widgetSettings,settingsLoadedAt=0;
function loadSettings(){
  if(widgetSettings&&Date.now()-settingsLoadedAt<300000)return widgetSettings;
  try{
    const cached=JSON.parse(sessionStorage.getItem(SETTINGS_KEY)||'null');
    if(cached?.agent===AGENT_ID&&cached.config&&Date.now()-cached.at<300000){settingsLoadedAt=cached.at;widgetSettings=Promise.resolve(cached.config);return widgetSettings}
  }catch{/* Storage can be unavailable in private browsing. */}
  settingsLoadedAt=Date.now();
  widgetSettings=fetch(`https://api.elevenlabs.io/v1/convai/agents/${AGENT_ID}/widget`,{signal:AbortSignal.timeout(6000)})
    .then(response=>{if(!response.ok)throw new Error('Settings unavailable');return response.json()})
    .then(({widget_config:config})=>{
      if(!config)throw new Error('Settings unavailable');
      const adapted={...config,first_message:'Hi, I’m Alex. What would you like to understand about the Academy or your workspace?',
        avatar:config.avatar?.type==='orb'?{...config.avatar,color_1:'#789166',color_2:'#d8e5bb'}:config.avatar,
        styles:{...config.styles,base:'#141d18',base_hover:'#243229',base_active:'#2d3d30',base_primary:'#edf1e9',base_subtle:'#aab9ad',base_border:'#344638',accent:'#cdddac',accent_hover:'#dae8c0',accent_active:'#bbcea0',accent_primary:'#182315',overlay_padding:0,button_radius:10,input_radius:10,sheet_radius:14}};
      try{sessionStorage.setItem(SETTINGS_KEY,JSON.stringify({agent:AGENT_ID,at:Date.now(),config:adapted}))}catch{/* Optional public-settings cache. */}
      return adapted;
    }).catch(error=>{widgetSettings=null;throw error});
  return widgetSettings;
}

export function alexErrorMessage(raw='',mode='text'){
  const detail=String(raw).toLowerCase();
  if(/permission denied|permission dismissed|notallowederror|microphone.*(denied|blocked)|requested device not found|notfounderror/.test(detail))
    return 'Microphone access is unavailable. Allow it in your browser’s website settings, or choose Text Alex.';
  if(/network|offline|failed to fetch|websocket|connection.*(closed|failed)|timed out/.test(detail))
    return 'The connection was interrupted. Check your connection and try again. Your conversation is still here.';
  return mode==='voice'?'The call couldn’t connect. Try again, or choose Text Alex to keep getting help.':'Alex couldn’t connect. Try again, or contact the Academy team.';
}

// Widget 0.18.3 strips audio tags from voice transcripts only. Its N2 renderer
// exclusively wraps agent replies in .pr-8 > .markdown; user bubbles do not use
// that structure. Remove only known leading delivery cues, never all brackets.
const ALEX_STAGE_PREFIX=/^(?:\s*\[(?:warmly|calmly|gently|softly|reassuringly|thoughtfully)\])+\s*/i;
export function refineAlexAgentStagePrefixes(root){
  let changes=0;
  root.querySelectorAll('.pr-8 > .markdown').forEach(markdown=>{
    const paragraph=markdown.firstElementChild;
    if(paragraph?.tagName!=='P')return;
    const nodes=[];
    // Keep semantic/literal content and links intact. Delivery cues can span
    // harmless emphasis, but must precede any code, link or other content.
    const collect=parent=>{
      for(const node of parent.childNodes){
        if(node.nodeType===3)nodes.push(node);
        else if(node.nodeType===1){
          if(!['SPAN','EM','STRONG','B','I'].includes(node.tagName)||!collect(node))return false;
        }
      }
      return true;
    };
    collect(paragraph);
    const prefix=nodes.map(node=>node.data).join('').match(ALEX_STAGE_PREFIX)?.[0];
    if(!prefix)return;
    let remaining=prefix.length;
    for(const node of nodes){
      if(!remaining)break;
      const count=Math.min(remaining,node.data.length);
      if(count){node.data=node.data.slice(count);remaining-=count;changes++}
    }
  });
  return changes;
}

// The pinned widget does not expose startup failures as a lifecycle event.
// Adapt its dedicated errors and the narrow agent-only text prefix above.
function refineWidget(widget,{mode,onError,onReady,onIdle}){
  const root=widget.shadowRoot;if(!root)return ()=>{};
  const styles=document.createElement('link');styles.rel='stylesheet';styles.href='/cinematic/alex-support.css?v=20261007-safari1';root.append(styles);
  let ready=false;const errors=new WeakMap();
  const inspect=()=>{
    refineAlexAgentStagePrefixes(root);
    if(!ready&&root.querySelector('textarea,button')){ready=true;onReady()}
    if(!root.querySelector('button[aria-label="End call"],button[aria-label="End chat"]'))onIdle();
    root.querySelectorAll('.text-base-error.text-center').forEach(node=>{
      if(!node.textContent.trim())return;
      const raw=node.textContent;
      if(errors.get(node)===raw)return;
      errors.set(node,raw);node.dataset.alexPrivate='';onError(alexErrorMessage(raw,mode));
    });
  };
  const observer=new MutationObserver(inspect);observer.observe(root,{subtree:true,childList:true,characterData:true});inspect();
  return ()=>observer.disconnect();
}
function loadWidget(){
  if(customElements.get('elevenlabs-convai'))return Promise.resolve();
  if(widgetScript)return widgetScript;
  widgetScript=new Promise((resolve,reject)=>{
    const script=document.createElement('script');
    const fail=()=>{clearTimeout(timeout);script.remove();widgetScript=null;reject(new Error('Alex could not load.'))};
    const timeout=setTimeout(fail,12000);
    script.src=WIDGET_URL;script.async=true;
    script.onload=()=>customElements.whenDefined('elevenlabs-convai').then(()=>{clearTimeout(timeout);resolve()});
    script.onerror=fail;document.head.append(script);
  });
  return widgetScript;
}

export function initAlexSupport({classroom=false,onTeam}={}){
  let launcher=document.querySelector('#alex'),host=null,cleanup=()=>{};
  if(!launcher){
    launcher=document.createElement('button');launcher.id='alex';launcher.type='button';
    launcher.innerHTML='<span class="alex-dot" aria-hidden="true"></span>Ask Alex';
    document.body.append(launcher);
  }
  launcher.setAttribute('aria-controls','alex-voice-host');
  launcher.setAttribute('aria-label','Ask Alex');
  launcher.setAttribute('aria-expanded','false');
  launcher.classList.add('academy-alex-launch');
  function close({focus=true}={}){
    cleanup();cleanup=()=>{};host?.remove();host=null;launcher.hidden=false;launcher.setAttribute('aria-expanded','false');
    if(focus)launcher.focus({preventScroll:true});
  }
  async function open(mode='text'){
    close({focus:false});
    const panel=document.createElement('section');host=panel;
    panel.id='alex-voice-host';panel.className='academy-alex-panel';
    panel.setAttribute('role','dialog');panel.setAttribute('aria-label','Ask Alex');
    panel.innerHTML=`<div class="alex-support-bar"><div><b>Ask Alex</b><small>Your AI Academy guide</small></div><button type="button" id="alex-mode">${mode==='text'?'Call Alex':'Text Alex'}</button><button type="button" id="alex-close" aria-label="Close Alex support"><svg class="academy-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><use href="/ui-icons.svg#close"></use></svg></button><nav aria-label="Alex help links"><a href="/#intelligence">Tool guides</a><a href="${classroom?'#library':'/#learn'}">Lessons</a>${onTeam?'<button type="button" id="alex-team">Academy team</button>':'<a href="/classroom#contact">Academy team</a>'}</nav><p class="alex-status" role="status">Opening Alex…</p></div>`;
    document.body.append(panel);launcher.hidden=true;launcher.setAttribute('aria-expanded','true');
    const bar=panel.querySelector('.alex-support-bar'),toggle=panel.querySelector('#alex-mode'),status=panel.querySelector('.alex-status');
    panel.querySelector('#alex-close').onclick=()=>close();
    panel.querySelector('#alex-close').focus({preventScroll:true});
    panel.addEventListener('keydown',e=>{if(e.key==='Escape'){e.stopPropagation();close()}});
    panel.querySelectorAll('a').forEach(link=>link.addEventListener('click',()=>close({focus:false})));
    // A hand-off opens the human inbox; it never forwards the Alex transcript.
    panel.querySelector('#alex-team')?.addEventListener('click',()=>confirmChange(()=>{close({focus:false});onTeam()},'Switch to the Academy team?','Your Alex conversation will end. Write your question to the team; this chat is not forwarded.','Message the team'));
    function confirmChange(action,title,description,label){
      if(panel.dataset.conversationStarted!=='true'){action();return}
      if(panel.querySelector('.alex-switch'))return;
      const prompt=document.createElement('div');prompt.className='alex-switch';prompt.setAttribute('role','group');prompt.setAttribute('aria-label',title);
      const heading=document.createElement('b');heading.textContent=title;
      const detail=document.createElement('p');detail.textContent=description;
      const confirm=document.createElement('button');confirm.type='button';confirm.textContent=label;confirm.onclick=action;
      const cancel=document.createElement('button');cancel.type='button';cancel.textContent='Keep this conversation';cancel.onclick=()=>{prompt.remove();toggle.focus()};
      prompt.append(heading,detail,confirm,cancel);bar.append(prompt);cancel.focus();
    }
    toggle.onclick=()=>confirmChange(()=>open(mode==='text'?'voice':'text'),'Switch conversation mode?','Switching ends this conversation and starts a new one.',mode==='text'?'Switch to calling':'Switch to text');
    toggle.disabled=true;
    try{
      const [,config]=await Promise.all([loadWidget(),loadSettings()]);if(!panel.isConnected)return;
      const widget=document.createElement('elevenlabs-convai');
      widget.setAttribute('override-config',JSON.stringify(config));
      const attributes={'agent-id':AGENT_ID,'variant':'full','default-expanded':'true','always-expanded':'true','dismissible':'false','override-text-only':String(mode==='text'),'text-input':'true','transcript':'true','show-avatar-when-collapsed':'false','show-agent-status':'false','strip-audio-tags':'true','worklet-path-libsamplerate':SAMPLERATE_URL,'show-conversation-id':'false','show-resize-button':'false','markdown-link-allowed-hosts':'protraderacademy.company,app.protraderacademy.company','markdown-link-allow-http':'false','allow-events':'true'};
      Object.entries(attributes).forEach(([key,value])=>widget.setAttribute(key,value));
      widget.setAttribute('text-contents',JSON.stringify({main_label:'Ask Alex',start_call:'Call Alex',start_chat:'Chat with Alex',end_call:'End call',new_call:'Call again',chatting_status:'Chatting with Alex',connecting_status:mode==='voice'?'Connecting your call…':'Connecting your conversation…',error_occurred:'Alex is unavailable',input_placeholder:'Ask Alex…',input_placeholder_text_only:'Ask Alex…',input_placeholder_new_conversation:'Ask Alex…'}));
      widget.addEventListener('elevenlabs-convai:call',event=>{
        const config=event.detail.config,previousConnect=config.onConnect;
        status.textContent=mode==='voice'?'Connecting your call…':'Connecting your conversation…';
        panel.dataset.connection='connecting';
        config.onConnect=(...args)=>{
          previousConnect?.(...args);panel.dataset.conversationStarted='true';panel.dataset.connection='connected';status.textContent=mode==='voice'?'Call connected. You can speak to Alex.':'Ask about the tools, lessons or your next step.';
          // Only shared public guidance. Do not read the signed-in page or session.
          setTimeout(()=>{if(widget.isConnected)widget.dispatchEvent(new CustomEvent('elevenlabs-agent:contextual-update',{detail:{message:ALEX_PRODUCT_CONTEXT}}))},0);
        };
      });
      const slot=document.createElement('div');slot.className='alex-widget-slot';slot.append(widget);panel.append(slot);toggle.disabled=false;
      const readyCopy=mode==='text'?'Ask about the tools, lessons or your next step.':'Tap the phone button to call. Your microphone starts only when you call.';
      const recovery=document.createElement('div');recovery.className='alex-recovery';recovery.hidden=true;
      const retry=document.createElement('button');retry.type='button';retry.textContent='Try again';
      retry.onclick=()=>confirmChange(()=>open(mode),'Start a new conversation?','Your current conversation will end. You can copy any information you want to keep first.','Start again');
      recovery.append(retry);bar.append(recovery);
      const stopRefinement=refineWidget(widget,{mode,onReady:()=>{status.textContent=readyCopy},onIdle:()=>{if(panel.dataset.connection==='connected'){panel.dataset.connection='ended';status.textContent=mode==='voice'?'Call ended. Call again or choose Text Alex.':'Conversation ended. Send a message to start again.'}},onError:message=>{panel.dataset.connection='error';status.textContent=message;recovery.hidden=false;toggle.disabled=false}});
      // Keep the composer above the on-screen keyboard and browser controls.
      const viewport=window.visualViewport;
      const fit=()=>{if(!panel.isConnected)return;panel.style.setProperty('--alex-available-height',`${viewport?.height||innerHeight}px`);panel.style.setProperty('--alex-keyboard-inset',`${Math.max(0,innerHeight-(viewport?.height||innerHeight)-(viewport?.offsetTop||0))}px`)};
      fit();viewport?.addEventListener('resize',fit);viewport?.addEventListener('scroll',fit);window.addEventListener('resize',fit);
      cleanup=()=>{stopRefinement();viewport?.removeEventListener('resize',fit);viewport?.removeEventListener('scroll',fit);window.removeEventListener('resize',fit)};
      status.textContent=readyCopy;
    }catch{
      if(!panel.isConnected)return;
      status.textContent='Alex couldn’t load. Check your connection, then try again or contact the Academy team.';
      toggle.disabled=false;
      const retry=document.createElement('button');retry.type='button';retry.textContent='Retry Alex';retry.onclick=()=>open(mode);bar.append(retry);
    }
  }
  launcher.addEventListener('pointerenter',()=>{loadWidget().catch(()=>{})},{once:true});
  launcher.addEventListener('focus',()=>{loadWidget().catch(()=>{})},{once:true});
  launcher.onclick=()=>open('text');
  window.addEventListener('academy-session-changed',()=>close({focus:false}));
  return {open,close,suspend(){close({focus:false});launcher.hidden=true},resume(){launcher.hidden=false;launcher.focus({preventScroll:true})}};
}
