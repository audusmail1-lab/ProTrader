// Public guides only. Lesson IDs and access rules remain owned by the classroom.
export const guideCategories = [
  {id:'all', name:'All guides', ids:[1,0,3,2,5,6,4], description:'Choose a guide for the tool you want to understand.'},
  {id:'getting-started', name:'Getting Started', ids:[1], description:'Begin with the public introduction, then learn to read and mark your chart.'},
  {id:'app-walkthroughs', name:'App Walkthroughs', ids:[2,5,6,4], description:'Explore the scanner, analysis views and optional desktop shortcuts.'},
  {id:'trade-execution', name:'Trade Execution', ids:[0,3], description:'Understand the paper ticket and journal. These guides do not connect a broker or submit a live trade.'},
  {id:'risk-management', name:'Risk Management', ids:[0,3,5,6], description:'Related guides on loss estimates, reviewing outcomes and understanding when to wait.'}
];
const escapeHtml = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

export function readLibraryLocation(hash) {
  const query = new URLSearchParams(hash.split('?')[1] || '');
  return {
    category: guideCategories.some(c => c.id === query.get('category')) ? query.get('category') : 'all',
    search: (query.get('q') || '').slice(0, 120)
  };
}

export function matchingGuides(videos, category, search = '') {
  const selected = guideCategories.find(c => c.id === category) || guideCategories[0];
  const words = search.toLocaleLowerCase().trim().split(/\s+/).filter(Boolean);
  return selected.ids.map(id => videos.find(v => v.id === id)).filter(Boolean).filter(v => {
    const content = [v.title, v.topic, v.summary, ...v.steps].join(' ').toLocaleLowerCase();
    return words.every(word => content.includes(word));
  });
}

export function categoryRibbon() {
  return `<nav class="guide-ribbon" aria-label="Explore learning guides">${guideCategories.slice(1).map(c=>`<a href="#library?category=${c.id}">${c.name} <span aria-hidden="true">↗</span></a>`).join('')}</nav>`;
}

export function videoLibrary(videos, card, hash) {
  const selection = readLibraryLocation(hash);
  const category = guideCategories.find(c=>c.id===selection.category);
  const rows = matchingGuides(videos, selection.category, selection.search);
  return `<section class="page-heading compact"><p class="eyebrow">PUBLIC VIDEO GUIDES</p><h1>Understand first.<br><em>Go deeper when ready.</em></h1><p>New to the Academy? Begin with the introduction. Then find a short, narrated guide for the task in front of you.</p><a class="button secondary" href="#start">Begin the basics ↗</a></section>
    <section class="library-section"><div class="library-tools"><label for="guide-search">Find a guide<input id="guide-search" type="search" maxlength="120" value="${escapeHtml(selection.search)}" placeholder="Search charts, tickets, ARIA…" aria-controls="guide-results"></label><div class="guide-filters" role="group" aria-label="Guide categories">${guideCategories.map(c=>`<button type="button" data-guide-category="${c.id}" aria-pressed="${c.id===selection.category}">${c.name}</button>`).join('')}</div><p id="guide-category-description">${category.description}</p><p id="guide-result-count" role="status" aria-live="polite">${rows.length} ${rows.length===1?'guide':'guides'}</p></div><div id="guide-results" class="video-grid">${rows.length?rows.map(card).join(''):emptyState()}</div></section>`;
}

function emptyState() {
  return '<div class="guide-empty"><h2>No matching guides</h2><p>Try another topic, or clear the search and browse all seven guides.</p><button type="button" class="button secondary" data-reset-guides>Show all guides</button></div>';
}

export function bindVideoLibrary(main, videos, card, openVideo) {
  const input = main.querySelector('#guide-search');
  if (!input) return;
  let {category} = readLibraryLocation(location.hash);
  const update = () => {
    const rows = matchingGuides(videos, category, input.value);
    const chosen = guideCategories.find(c=>c.id===category);
    main.querySelectorAll('[data-guide-category]').forEach(b=>b.setAttribute('aria-pressed', String(b.dataset.guideCategory===category)));
    main.querySelector('#guide-category-description').textContent = chosen.description;
    main.querySelector('#guide-result-count').textContent = `${rows.length} ${rows.length===1?'guide':'guides'}`;
    const results = main.querySelector('#guide-results');
    results.innerHTML = rows.length ? rows.map(card).join('') : emptyState();
    results.querySelectorAll('[data-video]').forEach(b=>b.onclick=()=>openVideo(Number(b.dataset.video)));
    results.querySelector('[data-reset-guides]')?.addEventListener('click',()=>{category='all';input.value='';update();input.focus()});
    const query = new URLSearchParams();
    if (category !== 'all') query.set('category', category);
    if (input.value.trim()) query.set('q', input.value.trim());
    history.replaceState(null, '', '#library'+(query.size?'?'+query.toString():''));
  };
  input.addEventListener('input', update);
  main.querySelectorAll('[data-guide-category]').forEach(b=>b.addEventListener('click',()=>{category=b.dataset.guideCategory;update()}));
  // Also wires the empty state when a saved search was opened directly.
  main.querySelector('[data-reset-guides]')?.addEventListener('click',()=>{category='all';input.value='';update();input.focus()});
}
