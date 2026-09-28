(()=>{
const $=s=>document.querySelector(s),escape=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
// Collapse the long library without destroying player controls or media.
const library=$('#learn'),toggle=document.createElement('button');toggle.className='library-toggle';toggle.id='library-toggle';toggle.setAttribute('aria-expanded','false');toggle.setAttribute('aria-controls','video-library-body');toggle.innerHTML='Explore all 10 videos <span>＋</span>';
const body=document.createElement('div');body.id='video-library-body';body.hidden=true;const filters=library.querySelector('.filter-group');const context=library.querySelector('.library-context');const grid=library.querySelector('.lesson-grid');[filters,context,grid].forEach(e=>body.appendChild(e));library.querySelector('.section-heading').appendChild(toggle);library.appendChild(body);toggle.onclick=()=>{body.hidden=!body.hidden;toggle.setAttribute('aria-expanded',String(!body.hidden));toggle.innerHTML=body.hidden?'Explore all 10 videos <span>＋</span>':'Collapse video library <span>−</span>'};
})();
