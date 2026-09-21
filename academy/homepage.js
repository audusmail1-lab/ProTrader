// Academy homepage adapted from the supplied Pro Trader landing-page design.
export function academyHome({ state, lessons, videos, introVideo, videoCard, esc, enrollmentLabel }) {
  const app = state.appUrl ? esc(state.appUrl) : '';
  const corners = '<i class="corner tl"></i><i class="corner tr"></i><i class="corner bl"></i><i class="corner br"></i>';
  const appLink = (label, secondary = false) => app ? `<a class="button ${secondary ? 'secondary' : ''}" href="${app}">${label} <span aria-hidden="true">↗</span></a>` : '';
  return `<div class="academy-landing">
    <section class="landing-hero">
      <div class="landing-copy">
        <p class="eyebrow">PRO TRADER ACADEMY / LEARN · PRACTICE · REVIEW</p>
        <h1>Learn the tools.<br><span>Practise with<br>purpose.</span></h1>
        <p class="landing-lede">Start with a short introduction to Pro Trader Academy. See how the trading workspace, guided practice and instructor support fit together—then choose your next step.</p>
        <div class="actions"><button class="button" data-video="7">Watch the introduction <span aria-hidden="true">▶</span></button><a class="button secondary" href="#start">Try the beginner guide <span aria-hidden="true">↗</span></a></div>
        <p class="landing-note">1 minute 27 seconds · No sign-in needed · Transcript available</p>
      </div>
      <div class="hero-introduction blueprint">${corners}<div class="frame-caption"><span>START HERE / MEET YOUR ACADEMY</span><span>${esc(introVideo.duration)}</span></div><button class="landing-film-preview" data-video="7" aria-label="Watch the Academy introduction, ${esc(introVideo.duration)}"><img src="${introVideo.poster}" alt="" width="1920" height="1080" fetchpriority="high"><span class="film-play"><span aria-hidden="true">▶</span> Meet Pro Trader Academy</span></button><p class="intro-caption">What it is. How it helps. Where to begin.</p></div>
    </section>
    <section class="landing-overview" aria-label="Academy at a glance"><div class="overview-row"><div><strong>07</strong><span>Guided sessions</span></div><div><strong>$0</strong><span>Current academy access</span></div><div><strong>Practice first</strong><span>Begin with simulated exercises</span></div></div></section>
    <section class="landing-method"><div class="landing-section-head"><p class="eyebrow">01 / THE PROCESS</p><h2>One idea.<br>Then put it to work.</h2></div><div class="method-grid">
      <article><span class="method-number">01 — LEARN</span><h3>Understand the screen.</h3><p>Short lessons explain charts, the trade ticket and the app’s analysis in plain language.</p><a href="#start">Try the introduction ↗</a></article>
      <article><span class="method-number">02 — PRACTICE</span><h3>Make it concrete.</h3><p>Work through supplied examples and practice exercises before making decisions with real money.</p>${app ? `<a href="${app}">Explore the terminal ↗</a>` : '<a href="#start">Explore an example ↗</a>'}</article>
      <article><span class="method-number">03 — REVIEW</span><h3>Explain your decisions.</h3><p>Build a habit of reviewing your process. Accepted students can save lesson notes and ask their instructor questions.</p><a href="#classroom">Go to your classroom ↗</a></article>
    </div></section>
    <section class="landing-lessons"><div><p class="eyebrow">02 / YOUR FIRST WEEK</p><h2>A clear place<br>to begin.</h2><p>Seven guided sessions, from finding your way around to reviewing a complete practice workflow.</p><a class="button secondary" href="#start">Begin the introduction ↗</a><p class="lesson-access">The introduction and videos are public. Full classroom access follows instructor review and email verification.</p></div><ol class="landing-lesson-list">${lessons.map((lesson, index) => `<li><span>${String(index + 1).padStart(2, '0')}</span><h3>${esc(lesson.title)}</h3></li>`).join('')}</ol></section>
    <section class="landing-film landing-workspace">      <figure class="terminal-frame blueprint">${corners}
        <div class="frame-caption"><span>YOUR PRACTICE WORKSPACE</span><span>PRO TRADER / 01</span></div>
        ${app ? `<a href="${app}" aria-label="Open the separate Pro Trader trading app">` : ''}<img src="/landing-assets/landing-terminal.webp" srcset="/landing-assets/landing-terminal-800.webp 800w, /landing-assets/landing-terminal.webp 1600w" sizes="(max-width: 600px) 92vw, 620px" width="1600" height="1039" alt="Pro Trader terminal showing a chart, market list and analysis panels; illustrative interface screenshot" loading="lazy">${app ? '</a>' : ''}
        <figcaption><span>Learn the controls. Put the lesson into practice.</span><span>ILLUSTRATIVE SCREEN</span></figcaption>
      </figure><div><p class="eyebrow">03 / YOUR PRACTICE WORKSPACE</p><h2>From explanation<br>to experience.</h2><p>Use the Pro Trader terminal to explore the controls you’ve seen in the lessons. Begin in practice mode and get familiar with the screen at your own pace.</p>${appLink('Explore the terminal')}</div></section>
    <section class="landing-videos"><div class="landing-section-head"><div><p class="eyebrow">04 / FIELD NOTES</p><h2>Your tools, explained.</h2></div><a class="button secondary" href="#library">Explore all seven videos ↗</a></div><div class="video-grid">${[videos[1], videos[0], videos[3]].map(videoCard).join('')}</div></section>
    <section class="landing-enroll"><div><p class="eyebrow">TAKE THE NEXT STEP</p><h2>Build your process.<br>Learn with guidance.</h2><p>${state.enrollmentOpen ? 'Applications are open for the current free intake, for adults 18+. Your instructor reviews each application and confirms the next steps.' : 'Applications are opening soon. Start with the public introduction and videos while you wait.'} Confirmed class times and joining links appear in your classroom.</p></div><a class="button" href="#enroll">${esc(enrollmentLabel())} ↗</a></section>
    <p class="landing-boundary">The Academy and trading app have separate accounts. Academy enrollment does not create a broker account or place trades.</p>
  </div>`;
}
