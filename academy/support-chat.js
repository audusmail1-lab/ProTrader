const instructorDrafts=new Map();
window.addEventListener('academy-session-changed',()=>instructorDrafts.clear());
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const key=()=>crypto.randomUUID();
// One bounded transport for classroom and support. Never retry a write here:
// the server may have saved it even when its response cannot reach the browser.
export async function academyRequest(path,data,{timeoutMs=12000}={}){
  const writing=data!==undefined,controller=new AbortController();
  const uncertain='We could not confirm the result. Check whether it saved before trying again.';
  const timer=setTimeout(()=>controller.abort(),timeoutMs);
  try{
    const response=await fetch('/api/'+path,{method:writing?'POST':'GET',headers:writing?{'Content-Type':'application/json'}:{},body:writing?JSON.stringify(data):undefined,signal:controller.signal});
    const result=await response.json();
    if(!response.ok){
      const message=response.status>=500?(writing?uncertain:'This service is temporarily unavailable. Please try again.'):typeof result?.error==='string'?result.error:'We could not complete that request. Please try again.';
      const error=new Error(message);error.status=response.status;error.requestUncertain=writing&&response.status>=500;throw error;
    }
    return result;
  }catch(error){
    if(error.status)throw error;
    const message=writing?uncertain:controller.signal.aborted?'This is taking longer than expected. Check your connection and try again.':'We could not connect. Check your connection and try again.';
    const unavailable=new Error(message);unavailable.requestUncertain=writing;throw unavailable;
  }finally{clearTimeout(timer)}
}
const api=academyRequest;
const time=t=>new Date(t*1000).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});
function messagesHTML(messages,inbox=false){return messages.map(m=>`<article class="chat-message chat-${m.role}"><small>${esc({visitor:inbox?'Student / visitor':'You',human:'Academy team',assistant:'AI assistant',system:'Support update'}[m.role]||m.role)} · ${time(m.created)}</small><p>${esc(m.body)}</p></article>`).join('')}
export function initSupport({humanOnly=false,showLauncher=true,onOpen=()=>{},onClose=()=>{}}={}){const root=document.createElement('div');root.id='academy-chat';root.innerHTML=`<button id="chat-launch" aria-expanded="false" aria-controls="chat-window"><svg class="academy-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><use href="/ui-icons.svg#mail"></use></svg> <span>Need help?</span></button><section id="chat-window" role="dialog" aria-label="Academy support chat" hidden><div class="chat-header"><div><b>Academy support</b><small id="chat-status">Messages and guidance</small></div><button id="chat-close" aria-label="Close support chat"><svg class="academy-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><use href="/ui-icons.svg#close"></use></svg></button></div><div class="chat-intro"><p>Ask about the Academy, classes, or your account. Avoid passwords and financial information.</p><label id="chat-ai-choice" hidden><input type="checkbox" id="chat-ai-consent"> Use AI help. My chat messages may be sent to OpenAI. I can choose a human instead.</label><p><a href="#privacy">Privacy policy</a> · Guests: keep this browser to see replies, or sign in to keep conversations with your account.</p></div><div id="chat-messages" role="log" aria-live="polite" aria-relevant="additions"></div><p id="chat-error" role="status"></p><button type="button" id="chat-retry" class="button secondary small" hidden>Retry connection</button><form id="chat-form"><label for="chat-body" class="chat-label">Your message</label><textarea id="chat-body" maxlength="3000" rows="2" required placeholder="How can we help?"></textarea><div class="chat-actions"><button type="button" id="chat-human">Talk to a person</button><button type="submit" id="chat-send">Send</button></div></form></section>`;document.body.append(root);const q=s=>root.querySelector(s);let current=null,busy=false,timer=null,last='',pending=null,sessionVersion=0,identityReady=false;
q('#chat-launch').hidden=!showLauncher;q('#chat-human').hidden=humanOnly;root.classList.toggle('team-support',humanOnly);if(humanOnly){q('.chat-header b').textContent='Academy team';q('.chat-intro p').textContent='Account or class question? Leave a message for the team. Replies may not be immediate. Avoid passwords and financial information.'}
function paint(data){current=data;q('#chat-ai-choice').hidden=humanOnly||!data.aiAvailable;const labels={new:data.aiAvailable?'AI help or a person — your choice':'Human support · Leave a message',ai:'AI assistant · Ask a person any time',assistant_pending:'AI assistant is preparing a reply…',waiting:'Waiting for a human reply',human:'Academy team replied',closed:'Conversation resolved · Send to reopen'};q('#chat-status').textContent=humanOnly&&['new','ai','assistant_pending'].includes(data.status)?'Human support · Leave a message':labels[data.status]||'Academy support';const signature=JSON.stringify(data.messages);if(signature!==last){q('#chat-messages').innerHTML=messagesHTML(data.messages);q('#chat-messages').scrollTop=q('#chat-messages').scrollHeight;last=signature}}
let refreshing=null,openVersion=0;
function syncSend(){q('#chat-send').disabled=q('#chat-human').disabled=busy||!identityReady}
async function refresh(){
 if(q('#chat-window').hidden||busy)return;
 if(refreshing?.version===sessionVersion)return refreshing.promise;
 const request={version:sessionVersion};refreshing=request;
 q('#chat-retry').hidden=true;
 if(!identityReady)q('#chat-error').textContent='Connecting… You can write your message while we connect.';
 syncSend();
 request.promise=(async()=>{
  try{
   const data=await api('support');if(request.version!==sessionVersion)return;
   identityReady=true;paint(data);q('#chat-error').textContent='';
  }catch(e){
   if(request.version!==sessionVersion)return;
   q('#chat-error').textContent=identityReady?'Unable to refresh. Your messages will appear when the connection returns.':'We could not connect. Your draft is safe. Try connecting again.';
   q('#chat-retry').hidden=false;
  }finally{
   if(refreshing===request)refreshing=null;
   if(request.version===sessionVersion)syncSend();
  }
 })();
 return request.promise;
}
q('#chat-retry').onclick=()=>refresh();
syncSend();
function close(){openVersion++;q('#chat-window').hidden=true;q('#chat-launch').setAttribute('aria-expanded','false');clearInterval(timer);if(showLauncher)q('#chat-launch').focus();onClose()}
async function open(){const version=++openVersion;onOpen();q('#chat-window').hidden=false;q('#chat-launch').setAttribute('aria-expanded','true');q('#chat-body').focus();clearInterval(timer);await refresh();if(version!==openVersion||q('#chat-window').hidden)return;timer=setInterval(refresh,5000)};q('#chat-launch').onclick=open;q('#chat-close').onclick=close;root.addEventListener('keydown',e=>{if(e.key==='Escape')close()});root.querySelector('a[href="#privacy"]').onclick=close;
async function send(human=humanOnly){if(busy||!identityReady)return;const body=q('#chat-body').value.trim()||(human&&!humanOnly?'I would like to speak to a human support agent.':'');if(!body)return;const version=sessionVersion;busy=true;q('#chat-send').disabled=q('#chat-human').disabled=true;q('#chat-error').textContent='Sending…';if(!pending||pending.body!==body||pending.human!==human)pending={body,human,clientId:key(),aiConsent:!humanOnly&&q('#chat-ai-consent').checked};try{const data=await api('support-message',pending);if(version!==sessionVersion)return;paint(data);q('#chat-body').value='';pending=null;q('#chat-error').textContent=''}catch(e){if(version===sessionVersion)q('#chat-error').textContent=e.message+' Your draft is still here.'}finally{if(version===sessionVersion){busy=false;syncSend()}}}
document.addEventListener('click',e=>{if(e.target.closest('[data-open-support]'))open()});
q('#chat-form').onsubmit=e=>{e.preventDefault();send()};q('#chat-human').onclick=()=>send(true);
window.addEventListener('academy-session-changed',()=>{sessionVersion++;identityReady=false;busy=false;current=null;last='';pending=null;syncSend();q('#chat-messages').replaceChildren();q('#chat-body').value='';q('#chat-ai-consent').checked=false;close()});
return {open,close};
}
export function supportInbox(){return `<section class="page-heading compact"><p class="eyebrow">HUMAN SUPPORT INBOX</p><h1>Keep the conversation<br><em>in one place.</em></h1><p>Students and guests receive your replies in the website chat. Verified students are also notified by email. No automatic response-time promise is shown.</p></section><section class="support-inbox"><aside class="panel"><button class="button secondary" id="support-refresh">Refresh conversations</button><div id="support-threads"></div></aside><article class="panel" id="support-thread"><p>Select a conversation to read and reply.</p></article></section>`}
export async function bindSupportInbox(){let active=null,timer,replyKey=null;const list=document.querySelector('#support-threads'),pane=document.querySelector('#support-thread');if(!list)return;const showError=e=>{let node=document.querySelector('#support-inbox-error');if(!node){node=document.createElement('p');node.id='support-inbox-error';list.before(node)}node.textContent=e.message};async function loadList(){try{const data=await api('support-admin');list.innerHTML=data.threads.map(t=>`<button class="support-thread-button" data-thread="${t.id}"><b>${esc(t.name||'Guest')} · #${t.id}</b><small>${esc(t.status.replaceAll('_',' '))} · ${new Date(t.updated*1000).toLocaleString()}</small></button>`).join('')||'<p>No support conversations yet.</p>'}catch(e){showError(e)}}
async function loadThread(id){try{const data=await api('support-admin-thread',{thread:id});if(active!==id)return;const old=instructorDrafts.get(id)||'';pane.innerHTML=`<h2>Conversation #${id}</h2><div class="inbox-messages">${messagesHTML(data.messages,true)}</div><form id="support-reply-form"><label for="support-reply">Reply as the Academy team</label><textarea id="support-reply" rows="4" maxlength="3000" required>${esc(old)}</textarea><p id="support-reply-status" role="status"></p><button class="button" type="submit">Send human reply</button><button class="button secondary" type="button" id="support-resolve">Mark resolved</button></form>`;document.querySelector('#support-reply').oninput=e=>instructorDrafts.set(id,e.target.value);document.querySelector('#support-reply-form').onsubmit=async e=>{e.preventDefault();const b=e.submitter,body=document.querySelector('#support-reply').value.trim();if(!body)return;b.disabled=true;if(!replyKey||replyKey.body!==body)replyKey={body,clientId:key()};try{await api('support-admin-reply',{thread:id,...replyKey});document.querySelector('#support-reply').value='';instructorDrafts.delete(id);replyKey=null;await loadThread(id);await loadList()}catch(err){document.querySelector('#support-reply-status').textContent=err.message;b.disabled=false}};document.querySelector('#support-resolve').onclick=async()=>{try{await api('support-admin-close',{thread:id});await loadList();document.querySelector('#support-reply-status').textContent='Conversation marked resolved.'}catch(e){document.querySelector('#support-reply-status').textContent=e.message}}}catch(e){showError(e)}}
list.onclick=e=>{const b=e.target.closest('[data-thread]');if(b){if(active!==+b.dataset.thread){active=+b.dataset.thread;replyKey=null;pane.innerHTML=''}loadThread(active)}};document.querySelector('#support-refresh').onclick=()=>{loadList();if(active)loadThread(active)};await loadList();}
