/* Preview media refinements. Original URLs retained for rollback. */
(()=>{
const videos=window.academyVideos;
const lessons={
'Chart essentials':['Start with context.','A candle summarizes the open, high, low and close for one time interval. A larger timeframe gives context; a smaller one shows more detail.','Choose a timeframe for your decision.','Mark the level that would invalidate your idea.','Keep the chart readable: every drawing should answer a question.'],
'ARIA & Oracle, explained':['Agreement isn’t certainty.','ARIA checks defined market conditions. Oracle summarizes how many agree. Eight of ten conditions means 80% agreement—not an 80% chance of winning.','Read the failed checks as carefully as the passed ones.','Confirm that every input uses verified, current data.','Use the score as context, never as a substitute for a risk plan.'],
'Plan your risk':['Start with what you can lose.','In this EUR/USD example, a 20-pip stop at 0.50 lots represents approximately $100 of price risk on a USD account, before fees and slippage.','Set the level where the idea stops making sense.','Choose your risk budget, then calculate size.','Check actual risk again after moving your stop.']};

const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const order=[8,1,0,2,5,6,3,4,9,7];
const grid=document.querySelector('.lesson-grid');
const oldLabels={0:'Plan your risk',1:'Chart essentials',6:'ARIA & Oracle, explained'};
grid.innerHTML=order.map(id=>{const v=videos.find(x=>x.id===id);return `<button class="lesson-card video-library-card" data-lesson="${esc(oldLabels[id]||v.title)}" data-video="${id}" data-kind="${v.kind}"><div class="video-thumbnail ${id<7?'portrait-thumb':''}"><img src="${esc(v.poster)}" alt="" loading="lazy" width="${id<7?'1080':'1920'}" height="${id<7?'1920':'1080'}"><span class="video-play" aria-hidden="true">↗</span><span class="video-duration">${v.duration}</span></div><div class="lesson-info"><small>${esc(v.topic.toUpperCase())} · GUIDE + VIDEO</small><h3>${esc(v.title)} <span>↗</span></h3><p>${esc(v.summary)}</p>${!v.refined&&v.reviewStatus!=='Keep'?'<span class="video-review-tag">Earlier interface · Read update note</span>':''}</div></button>`}).join('');
document.querySelectorAll('[data-video]').forEach(b=>b.onclick=()=>openDescription(+b.dataset.video));
const filters=document.querySelector('.library .filter-group');filters.innerHTML='<button class="selected" data-video-filter="all">All 10 videos</button><button data-video-filter="foundation">Foundations</button><button data-video-filter="tools">Tools</button><button data-video-filter="orientation">Getting started</button>';
document.querySelectorAll('[data-video-filter]').forEach(b=>b.onclick=()=>{document.querySelectorAll('[data-video-filter]').forEach(x=>x.classList.toggle('selected',x===b));document.querySelectorAll('[data-video]').forEach(c=>c.hidden=b.dataset.videoFilter!=='all'&&c.dataset.kind!==b.dataset.videoFilter)});
const intro=document.createElement('p');intro.className='library-context';intro.textContent='Start with a written explanation, then watch the video or try a practice task. Narrated by Callan. Useful original footage is retained; recording notes explain any differences from the current interface.';document.querySelector('.library .section-heading').after(intro);
document.querySelector('#tour').innerHTML='Watch the overview <span>▷ 0:49</span>';document.querySelector('#tour').onclick=()=>openVideo(8);document.querySelector('#visual-tour').setAttribute('aria-label','Watch the Academy overview narrated by Callan');document.querySelector('#visual-tour').onclick=()=>openVideo(8);
// Preserve accurate enrollment expectations alongside the refreshed visuals.
const nav=document.querySelector('.site-header nav');const appLink=document.createElement('button');appLink.textContent='Open app ↗';appLink.onclick=()=>showPage('terminal');nav.appendChild(appLink);
// Make the risk explanation available without expanding the video library.
const riskLink=document.createElement('button');riskLink.className='risk-explainer-link';riskLink.textContent='Understand risk & position size →';riskLink.setAttribute('aria-haspopup','dialog');riskLink.onclick=()=>openDescription(0);document.querySelector('.hero-visual').appendChild(riskLink);
document.addEventListener('academy:guide',e=>{if(videos.some(v=>v.id===e.detail))openDescription(e.detail)});
function openDescription(id){
 const v=videos.find(x=>x.id===id), original=lessons[oldLabels[id]];
 modal.querySelector('video')?.pause();modal.classList.remove('video-dialog');
 const title=oldLabels[id]||v.title;
 const explanation=original?`<p><strong>${esc(original[0])}</strong></p><p>${esc(original[1])}</p><ol>${original.slice(2).map(t=>`<li>${esc(t)}</li>`).join('')}</ol>`:`<p>${esc(v.summary)}</p><ol>${v.steps.map(t=>`<li>${esc(t)}</li>`).join('')}</ol>`;
 openModal(title,`${explanation}<section class="written-practice"><b>Try one thing</b><p>${esc(v.practice)}</p></section>${!v.refined&&v.reviewStatus!=='Keep'?`<details class="written-update"><summary>About this recording</summary><p>${esc(v.reviewNote)}</p></details>`:''}<div class="written-actions"><button class="dark-button" id="watch-lesson">Watch video <span>▷ ${v.duration}</span></button>${[0,3,5,6].includes(id)?'<button class="text-button" id="written-practise">Try in the workspace →</button>':''}</div><p class="written-footnote">Read at your pace. The video is optional and includes captions and a transcript.</p>`,'UNDERSTAND · WATCH · PRACTISE');
 $('#watch-lesson').onclick=()=>openVideo(id);
 if($('#written-practise'))$('#written-practise').onclick=showPage;
 modal.scrollTop=0;$('#close-modal').focus();
}
document.addEventListener('academy:watch-lesson',event=>{if(videos.some(v=>v.id===event.detail))openVideo(event.detail)});
function openVideo(id){
 const v=videos.find(x=>x.id===id),portrait=id<7||(id===7&&innerWidth<600),source=id===7&&portrait?v.formats.portrait.url:v.url,poster=id===7&&portrait?v.formats.portrait.poster:v.poster;
 modal.classList.add('video-dialog');
 openModal(v.title,`<button class="text-button back-to-description" id="back-to-description">← Back to written guide</button>${!v.refined&&[5,6,7].includes(id)?'<p class="recording-alert"><strong>Earlier-model recording:</strong> this film shows nine checks. The reviewed engine uses ten. Read the correction alongside the video; the original recording is preserved.</p>':''}<div class="video-layout"><div class="video-stage ${portrait?'portrait-video':''}"><video id="lesson-video" controls playsinline preload="auto" poster="${esc(poster)}" aria-label="${esc(v.title)}"><source src="${esc(source)}" type="video/mp4"><track kind="captions" src="${esc(v.captions)}" srclang="en" label="English"><p>Your browser cannot play this video. Read the transcript alongside it.</p></video><p id="video-status" class="video-playback-status" role="status">Press play when you’re ready.</p><div id="video-error" hidden><p>Video could not load. Your written guide and transcript are still available.</p><button class="text-button" id="retry-video">Retry video</button></div></div><aside class="video-notes"><span class="eyebrow">${v.duration} · CALLAN · ACADEMY FILM</span><p>${esc(v.summary)}</p><section class="video-current-note"><b>${v.reviewStatus==='Keep'?'Before you practise':'Recording update note'}</b><p>${esc(v.reviewNote)}</p></section><section class="video-exercise"><b>Try one thing</b><p>${esc(v.practice)}</p></section><p class="video-original-note">${esc(v.note)}</p>${id===6||id===5?'<button class="dark-button" id="video-practice">Open analysis in PROTrader ↗</button>':id===0?'<button class="dark-button" id="video-practice">Try the risk planner ↗</button>':id===3?'<button class="dark-button" id="video-practice">Write a practice note ↗</button>':''}</aside></div><details class="video-transcript"><summary>Read transcript & jump to a section</summary><p>Transcript matching the revised narration. Select a time to revisit that section.</p>${v.transcript.map(t=>`<div><button data-video-time="${t.at}" aria-label="Jump to ${esc(t.time)}">${esc(t.time)}</button><p>${esc(t.text)}</p></div>`).join('')}</details>${v.credit?`<p class="music-credit">Music: <a href="${esc(v.credit.source)}" target="_blank" rel="noopener">${esc(v.credit.text)}</a> · <a href="${esc(v.credit.license)}" target="_blank" rel="noopener">CC BY 4.0</a></p>`:''}`,'WATCH · UNDERSTAND · PRACTISE');
 $('#back-to-description').onclick=()=>openDescription(id);modal.scrollTop=0; const player=document.querySelector('#lesson-video');const status=document.querySelector('#video-status'),error=document.querySelector('#video-error');
 const fail=()=>{error.hidden=false;status.textContent='Video unavailable. Try again or read the transcript.'};
 player.addEventListener('error',fail);player.querySelector('source').addEventListener('error',fail);
 player.addEventListener('waiting',()=>{status.textContent='Loading video…'});
 player.addEventListener('canplay',()=>{if(player.paused&&!player.ended)status.textContent='Press play when you’re ready.'});
 player.addEventListener('playing',()=>{error.hidden=true;status.textContent='Use CC for captions. Pause to try a step.'});
 player.addEventListener('ended',()=>{status.textContent='Video complete. Return to the written guide to practise.'});
 document.querySelector('#retry-video').onclick=()=>{error.hidden=true;status.textContent='Loading video…';player.load();player.play().catch(()=>{status.textContent='Press play to continue.'})};
 player.querySelector('track').addEventListener('error',()=>{status.textContent='Captions unavailable. Read the transcript below.'});
 document.querySelectorAll('[data-video-time]').forEach(b=>b.onclick=()=>{player.currentTime=+b.dataset.videoTime;player.focus()});const practice=document.querySelector('#video-practice');if(practice)practice.onclick=showPage;
}
modal.addEventListener('close',()=>{const v=modal.querySelector('video');if(v){v.pause();v.removeAttribute('src');v.querySelectorAll('source').forEach(s=>s.removeAttribute('src'));v.load()}modal.classList.remove('video-dialog')});
})();
