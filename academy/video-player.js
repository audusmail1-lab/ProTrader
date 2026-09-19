// Public tutorial player. Lesson access and saved progress remain server-owned.
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

export function createVideoPlayer(videos) {
  const dialog = document.querySelector('#player');
  const content = document.querySelector('#player-content');
  let opener;
  dialog.querySelector('.close').addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => {
    content.querySelector('video')?.pause();
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
    const format = v.formats && !window.matchMedia('(max-width: 760px)').matches ? 'landscape' : 'portrait';
    const media = v.formats?.[format] || v;
    dialog.classList.toggle('intro-player', Boolean(v.formats));
    dialog.dataset.format = format;
    dialog.querySelector('.player-toolbar span').textContent = v.formats ? 'ACADEMY / START HERE' : 'TUTORIAL / AT YOUR PACE';
    opener = document.activeElement;
    document.querySelectorAll('video').forEach(video => video.pause());
    content.innerHTML = `
      <div class="tutorial-media">
        <video controls playsinline preload="metadata" poster="${esc(media.poster)}" aria-label="${esc(v.title)}" src="${esc(media.url)}">
          <track kind="captions" src="${esc(v.captions)}" srclang="en" label="English">
        </video>
        <p class="playback-status" role="status">Press play when you’re ready. Pause or use full screen at any time.</p>
        <p class="video-fallback" hidden>Video unavailable? <a href="${esc(media.url)}" target="_blank" rel="noopener">Open the video directly</a>, or read the full transcript below.</p>
      </div>
      <div class="guide">
        <p class="eyebrow">${esc(v.topic)} · ${esc(v.duration)} · Narrated</p>
        <h2 id="player-title">${esc(v.title)}</h2><p>${esc(v.summary)}</p>
        <ol>${v.steps.map(step => `<li>${esc(step)}</li>`).join('')}</ol>
        <div class="extension">${esc(v.note)}</div>
        ${v.formats ? '<a class="button" href="#start">Begin the basics ↗</a>' : ''}
        <details class="tutorial-transcript"><summary>Read the full transcript</summary>
          ${v.transcript.map(s => `<p><button type="button" data-seek="${s.at}" aria-label="Play from ${esc(s.time)}">${esc(s.time)}</button> ${esc(s.text)}</p>`).join('')}
        </details>
        ${v.credit ? `<p class="music-credit">Music: <a href="${esc(v.credit.source)}" target="_blank" rel="noopener">${esc(v.credit.text)}</a>, released under <a href="${esc(v.credit.license)}" target="_blank" rel="noopener">CC BY 4.0</a>. Excerpt edited and mixed beneath narration.</p>` : ''}
      </div>`;
    const video = content.querySelector('video');
    const status = content.querySelector('.playback-status');
    const fallback = content.querySelector('.video-fallback');
    const fail = () => {
      status.textContent = 'The video could not load. Your written guide is still available.';
      fallback.hidden = false;
      content.querySelector('details').open = true;
    };
    video.addEventListener('error', fail);
    video.addEventListener('waiting', () => { status.textContent = 'Loading video… You can read the transcript while it buffers.'; });
    video.addEventListener('playing', () => { status.textContent = 'Pause to try a step. Use CC for English captions.'; });
    video.addEventListener('ended', () => { status.textContent = v.formats ? 'Ready to begin? Choose Begin the basics below.' : 'Tutorial complete. Try the steps at your own pace.'; });
    video.querySelector('track').addEventListener('error', () => {
      status.textContent = 'Captions could not load. The full transcript is available below.';
    });
    content.querySelectorAll('[data-seek]').forEach(button => button.addEventListener('click', () => {
      if (video.readyState === 0 || !Number.isFinite(video.duration)) {
        status.textContent = 'Press play to load the video, then choose a transcript time.';
        return;
      }
      video.currentTime = Math.min(Number(button.dataset.seek), video.duration);
      video.play().catch(() => { status.textContent = 'Press play on the video to continue.'; });
    }));
    dialog.showModal();
    document.body.classList.add('video-open');
    dialog.scrollTop = 0;
    // Explicit play avoids surprising narration when users open a written guide.
    if (video.error) fail();
  };
}
