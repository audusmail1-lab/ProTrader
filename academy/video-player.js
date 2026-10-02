// Public tutorial player. Lesson access and saved progress remain server-owned.
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

// Keep one chosen source while watching. Resizing must never restart a lesson.
export function selectVideoMedia(video,{mobile=false}={}){
  const format=video.formats?(mobile&&video.formats.portrait?'portrait':'landscape'):null;
  const media=video.formats?.[format]||video;
  const sources=[{url:media.url,width:media.width,height:media.height,label:media.height?`${media.height}p`:'Original'},...(media.sources||[])].filter((source,index,all)=>source.url&&all.findIndex(item=>item.url===source.url)===index);
  const baseline=sources.find(source=>source.height===720)||sources[0];
  const portrait=media.width&&media.height?media.height>media.width:format?format==='portrait':Number(video.id)<7;
  return {...media,url:baseline.url,sources,portrait,format:portrait?'portrait':'landscape'};
}

export function videoQualityHTML(media){
  if(media.sources.length<2)return '';
  return `<label class="lesson-quality">Video quality<select aria-label="Video quality"><option value="auto">${esc(media.sources.find(source=>source.url===media.url)?.label||'Standard')} · Recommended</option>${media.sources.map((source,index)=>source.url===media.url?'':`<option value="${index}">${esc(source.label||`${source.height}p`)}</option>`).join('')}</select></label>`;
}

export function releaseVideo(video){
  if(!video)return;
  video.pause();video.removeAttribute('src');
  video.querySelectorAll('source').forEach(source=>source.removeAttribute('src'));
  video.load();
}

// Optional reflection only: no score, account progress, network request or pause.
export const lessonPractice={
  0:{question:'With size fixed at 0.10 lots, what happens to target profit when only the stop moves closer?',answers:[
    {text:'Target profit stays the same.',feedback:'Size and target are unchanged, so estimated target profit stays $40 before costs. Moving the stop from 1.0980 to 1.0990 changes estimated loss from $20 to $10.'},
    {text:'Target profit increases automatically.',feedback:'Moving only the stop changes estimated loss. With size and target fixed, estimated target profit stays $40 before costs.'},
    {text:'The position automatically becomes larger.',feedback:'This is a fixed-size plan: it remains 0.10 lots. Only an explicitly chosen sizing mode would recalculate size; moving this stop does not.'}
  ]},
  1:{question:'What does your horizontal level represent?',answers:[
    {text:'A price area I can explain and observe.',feedback:'The level records your observation. Follow it across nearby candles and explain why that area matters; it does not guarantee a reaction.'},
    {text:'A price where the market must reverse.',feedback:'A drawn line cannot make the market reverse. It marks an area to observe, so keep the surrounding structure in view.'}
  ]},
  2:{question:'How should you use a detected pattern and its score?',answers:[
    {text:'As a cue to inspect the candles and surrounding structure.',feedback:'Review the marked candles and look for evidence that supports or contradicts the pattern. Record what remains unclear.'},
    {text:'As the probability that the next trade will win.',feedback:'A pattern score is a review cue, not a win probability. Inspect the chart context before drawing a conclusion.'},
    {text:'As a complete trade plan.',feedback:'A pattern result does not contain your complete reasoning or risk plan. Review its context and note the questions it leaves open.'}
  ]},
  3:{question:'Does a profitable paper result show that you followed your plan?',answers:[
    {text:'I still need to compare the result with my original reasoning.',feedback:'Profit alone cannot explain decision quality. Compare what happened with the plan you intended to follow, then save one useful reflection.'},
    {text:'Yes. Profit is enough to confirm the process.',feedback:'A positive result can follow an unplanned decision. Review the instrument, direction, closed volume and original reasoning as well as the profit.'}
  ]},
  4:{question:'How should you open ARIA when learning on a phone?',answers:[
    {text:'Use the visible navigation tabs.',feedback:'On a phone, use the visible tabs. The A and P shortcuts are for desktop; click outside text inputs before trying them there.'},
    {text:'Type A into any text field.',feedback:'Typing A in a text field enters text. Use the visible mobile navigation; desktop shortcuts start with focus outside an input.'}
  ]},
  5:{question:'ARIA shows six matching checks out of ten and a Wait verdict. What does the lesson ask you to do?',answers:[
    {text:'Inspect the unmet checks and explain why I waited.',feedback:'Keep the ticket unchanged in this exercise. Read the contradictory evidence and restrictions, then record why the verdict remains Wait.'},
    {text:'Ignore the unmet checks because most checks match.',feedback:'Matching checks do not erase contradictory evidence or restrictions. In this example the verdict is Wait, so review what is missing.'}
  ]},
  6:{question:'What does Oracle’s 80% mean in this example?',answers:[
    {text:'Eight of the same ten checks used by ARIA match.',feedback:'Eight divided by ten gives 80% agreement. Oracle summarises ARIA’s underlying checks; it is not an independent confirmation or a win probability.'},
    {text:'The trade has an 80% chance of winning.',feedback:'80% describes eight matching checks out of ten. It does not measure the probability of a successful trade.'},
    {text:'A separate system independently confirms ARIA.',feedback:'Oracle summarises the same underlying checks. Read the unmet conditions in ARIA rather than counting the two views as independent confirmations.'}
  ]},
  7:{question:'What role does Sentinel play in the workspace?',answers:[
    {text:'It monitors configured markets and timeframes using closed candles.',feedback:'Sentinel monitors those markets and timeframes and tracks paper outcomes. Monitoring adds context; it does not guarantee a forecast or result.'},
    {text:'It guarantees which market move happens next.',feedback:'Monitoring is not a guarantee. Sentinel reviews configured markets and timeframes using closed candles; you still need to interpret the evidence.'},
    {text:'It places my broker trades automatically.',feedback:'Sentinel’s role here is monitoring and paper-outcome tracking. It does not place your broker orders.'}
  ]},
  8:{question:'Which account do you use to sign in to PROTrader?',answers:[
    {text:'My Academy account, using the same email and password.',feedback:'Use your Academy email and password for PROTrader. The app creates its own session; joining the Academy does not open a broker account or connect MetaTrader.'},
    {text:'My broker account and MetaTrader credentials.',feedback:'PROTrader uses your Academy account. Broker and MetaTrader connections are separate; Academy enrollment does not create either connection.'},
    {text:'A new app account with different credentials.',feedback:'Use the same Academy email and password. The Academy and app maintain separate sessions, so an app sign-in does not require a second account.'}
  ]},
  9:{question:'A class invitation has changed. What should you check before joining?',answers:[
    {text:'The latest invitation, current classroom details and time zone.',feedback:'Compare the latest update with My classroom, including the topic, date, time zone and joining link. Ask the Academy team if the details still conflict.'},
    {text:'Only the first invitation I received.',feedback:'The first invitation may be out of date. Check the latest update and current classroom details, including the time zone, before using the joining link.'}
  ]}
};

export function lessonPracticeHTML(id){
  const practice=lessonPractice[id];if(!practice)return '';
  return `<details class="lesson-practice"><summary>Try what you learned <span>Optional</span></summary><fieldset><legend>${esc(practice.question)}</legend><div class="practice-answers">${practice.answers.map((answer,index)=>`<button type="button" data-practice-answer="${index}" aria-pressed="false">${esc(answer.text)}</button>`).join('')}</div></fieldset><p class="practice-feedback" role="status" aria-live="polite" aria-atomic="true"></p></details>`;
}

export function bindLessonPractice(root,id){
  const practice=lessonPractice[id];if(!root||!practice)return;
  const buttons=[...root.querySelectorAll('[data-practice-answer]')],feedback=root.querySelector('.practice-feedback');
  buttons.forEach(button=>button.addEventListener('click',()=>{
    const answer=practice.answers[Number(button.dataset.practiceAnswer)];if(!answer)return;
    buttons.forEach(item=>item.setAttribute('aria-pressed',String(item===button)));
    feedback.textContent=answer.feedback;
  }));
}

// An explicit chapter choice should reveal its film without moving keyboard
// focus or scrolling the page behind the dialog. Both players share this path.
function revealChapterVideo(video){
  const reducedMotion=video.ownerDocument?.defaultView?.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
  const behavior=reducedMotion?'auto':'smooth';
  const dialog=video.closest?.('dialog');
  if(!dialog){video.scrollIntoView?.({behavior,block:'start',inline:'nearest'});return}
  const frame=video.getBoundingClientRect(),bounds=dialog.getBoundingClientRect();
  const toolbar=dialog.querySelector('.player-toolbar, .modal-top');
  const inset=(toolbar?.getBoundingClientRect().height||0)+12;
  const top=bounds.top+dialog.clientTop+inset;
  const bottom=bounds.top+dialog.clientTop+dialog.clientHeight-12;
  if(frame.top>=top&&frame.bottom<=bottom)return;
  const position=Math.max(0,dialog.scrollTop+frame.top-top);
  if(dialog.scrollTo)dialog.scrollTo({top:position,behavior});
  else dialog.scrollTop=position;
}

// Shared lifecycle for homepage and classroom, including chapter navigation.
export function bindVideoPlayback({video,status,error,retry,chapters=[],quality,media,endedMessage='Lesson complete. Return to your guide and try the exercise.',stallMs=8000}){
  let disposed=false,timer=null,pendingSeek=null,shouldResume=false;
  const listeners=[];
  const on=(target,type,fn)=>{if(target){target.addEventListener(type,fn);listeners.push(()=>target.removeEventListener(type,fn))}};
  const clear=()=>{clearTimeout(timer);timer=null};
  const hideError=()=>{if(error)error.hidden=true};
  const showRecovery=message=>{if(disposed)return;clear();status.textContent=message;if(error)error.hidden=false};
  const waiting=()=>{
    if(disposed)return;
    status.textContent='Loading this part of the lesson…';
    if(timer===null)timer=setTimeout(()=>showRecovery('This is taking longer than expected. Retry from this point, or use the written guide.'),stallMs);
  };
  const play=()=>{
    if(disposed)return;
    video.preload='auto';
    try{Promise.resolve(video.play()).catch(error=>{if(disposed||error?.name==='AbortError')return;clear();if(error?.name==='NotAllowedError')status.textContent='Press play on the video to continue.';else showRecovery('The video could not start. Retry from this point, or use the written guide.')})}
    catch{status.textContent='Press play on the video to continue.'}
  };
  const applySeek=()=>{
    if(pendingSeek===null||video.readyState<1)return;
    const duration=Number.isFinite(video.duration)?video.duration:pendingSeek;
    video.currentTime=Math.max(0,Math.min(pendingSeek,duration));pendingSeek=null;
  };
  const seek=time=>{
    if(disposed||!Number.isFinite(Number(time)))return;
    pendingSeek=Math.max(0,Number(time));shouldResume=true;hideError();
    applySeek();play();
  };
  const reload=(source=video.currentSrc||video.getAttribute('src'))=>{
    if(disposed)return;
    const resume=shouldResume;
    pendingSeek=Number.isFinite(video.currentTime)?video.currentTime:0;
    hideError();clear();waiting();
    if(source){video.querySelectorAll('source').forEach(item=>item.removeAttribute('src'));video.src=source}
    video.load();shouldResume=resume;if(resume)play();
  };
  on(video,'play',()=>{shouldResume=true});
  on(video,'pause',()=>{if(video.paused&&!video.seeking){shouldResume=false;clear()}});
  on(video,'waiting',waiting);
  on(video,'stalled',()=>{if(!video.paused||pendingSeek!==null)waiting()});
  on(video,'loadedmetadata',()=>{applySeek();if(shouldResume&&video.paused)play()});
  on(video,'canplay',()=>{clear();hideError();if(video.paused&&!video.ended)status.textContent='Press play when you’re ready.'});
  on(video,'playing',()=>{clear();hideError();status.textContent='Use CC for captions. Pause to try a step.'});
  on(video,'ended',()=>{shouldResume=false;clear();status.textContent=endedMessage});
  const fail=()=>showRecovery('The video could not load. Retry from this point, or use the written guide.');
  on(video,'error',fail);video.querySelectorAll('source').forEach(source=>on(source,'error',fail));
  on(video.querySelector('track'),'error',()=>{status.textContent='Captions could not load. The full transcript is available below.'});
  on(retry,'click',()=>{shouldResume=true;reload()});
  for(const button of chapters)on(button,'click',()=>{seek(button.dataset.seek??button.dataset.videoTime);revealChapterVideo(video)});
  on(quality,'change',()=>{
    const source=quality.value==='auto'?media.sources.find(item=>item.url===media.url):media.sources[Number(quality.value)];
    if(!source||source.url===(video.currentSrc||video.getAttribute('src')))return;
    shouldResume=!video.paused&&!video.ended;reload(source.url);
  });
  if(video.error)fail();
  return {seek,dispose(){if(disposed)return;disposed=true;clear();listeners.forEach(remove=>remove());releaseVideo(video)}};
}

export function createVideoPlayer(videos) {
  const dialog = document.querySelector('#player');
  const content = document.querySelector('#player-content');
  let opener,playback;
  dialog.querySelector('.close').addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => {
    playback?.dispose();playback=null;
    content.replaceChildren();
    document.body.classList.remove('video-open');
    if (opener?.isConnected) opener.focus({preventScroll:true});
  });
  // Never leave two narrators playing, including the homepage preview.
  document.addEventListener('play', event => {
    if (event.target.tagName === 'VIDEO') {
      document.querySelectorAll('video').forEach(video => {
        if (video !== event.target) video.pause();
      });
    }
  }, true);
  window.addEventListener('hashchange', () => { if (dialog.open) dialog.close(); });
  return id => {
    const v = videos.find(video => video.id === id);
    if (!v) return;
    // Choose once when opened; resizing never restarts a viewer's playback.
    const media=selectVideoMedia(v,{mobile:window.matchMedia('(max-width: 760px)').matches});
    const format=media.format,intro=v.id===7;
    playback?.dispose();playback=null;
    dialog.classList.toggle('intro-player', intro);
    dialog.dataset.format = format;
    dialog.querySelector('.player-toolbar span').textContent = intro ? 'ACADEMY / START HERE' : 'TUTORIAL / AT YOUR PACE';
    opener = document.activeElement;
    document.querySelectorAll('video').forEach(video => video.pause());
    content.innerHTML = `
      <div class="tutorial-media">
        <video controls playsinline preload="metadata" poster="${esc(media.poster)}" aria-label="${esc(v.title)}" src="${esc(media.url)}">
          <track kind="captions" src="${esc(v.captions)}" srclang="en" label="English">
        </video>
        <p class="playback-status" role="status">Press play when you’re ready. Pause or use full screen at any time.</p>
        ${videoQualityHTML(media)}
        <p class="video-fallback" hidden><button type="button" class="text-button retry-lesson">Retry from this point</button> Video unavailable? <a href="${esc(media.url)}" target="_blank" rel="noopener">Open the video directly</a>, or read the full transcript below.</p>
        ${lessonPracticeHTML(id)}
      </div>
      <div class="guide">
        <p class="eyebrow">${esc(v.topic)} · ${esc(v.duration)} · Narrated</p>
        <h2 id="player-title">${esc(v.title)}</h2><p>${esc(v.summary)}</p>
        <ol>${v.steps.map(step => `<li>${esc(step)}</li>`).join('')}</ol>
        <div class="extension">${esc(v.note)}</div>
        ${intro ? '<a class="button" href="#start">Begin the basics</a>' : ''}
        <details class="tutorial-transcript"><summary>Read the full transcript</summary>
          ${v.transcript.map(s => `<p><button type="button" data-seek="${s.at}" aria-label="Play from ${esc(s.time)}">${esc(s.time)}</button> ${esc(s.text)}</p>`).join('')}
        </details>
        ${v.credit ? `<p class="music-credit">Music: <a href="${esc(v.credit.source)}" target="_blank" rel="noopener">${esc(v.credit.text)}</a>, released under <a href="${esc(v.credit.license)}" target="_blank" rel="noopener">CC BY 4.0</a>. Excerpt edited and mixed beneath narration.</p>` : ''}
      </div>`;
    const video = content.querySelector('video');
    const status = content.querySelector('.playback-status');
    const fallback = content.querySelector('.video-fallback');
    bindLessonPractice(content.querySelector('.lesson-practice'),id);
    playback=bindVideoPlayback({video,status,error:fallback,retry:content.querySelector('.retry-lesson'),chapters:content.querySelectorAll('[data-seek]'),quality:content.querySelector('.lesson-quality select'),media,endedMessage:intro?'Ready to begin? Choose Begin the basics below.':'Tutorial complete. Try the steps at your own pace.'});
    video.dataset.lessonId=String(id);
    document.dispatchEvent(new CustomEvent('academy:video-open',{detail:{id,video}}));
    dialog.showModal();
    document.body.classList.add('video-open');
    dialog.scrollTop = 0;
    // Explicit play avoids surprising narration when users open a written guide.

  };
}
