import { CatmullRomCurve3, Matrix4, PerspectiveCamera, Vector3 } from './vendor/three.core.js';
import { terminalHTML, heroChartHTML, heroChartState } from './terminal-preview.js?v=20260930-release2';

// Original hero choreography. Project the current HTML terminal onto the same
// 9.1 × 5.6 world-space console instead of loading the earlier GLB artwork.
export async function mountScene(surface, ready, { staticView = false } = {}) {
  const wrap = surface.parentElement;
  surface.innerHTML = terminalHTML();
  surface.className = 'workspace-display camera-projected';

  const camera = new PerspectiveCamera(37, 1, .1, 100);
  const curve = new CatmullRomCurve3([
    new Vector3(8, 10.8, 10), new Vector3(3.8, 9.8, 7),
    new Vector3(7.5, 8, 5), new Vector3(2.4, 9, 4.8),
    new Vector3(5, 11, 10)
  ], false, 'catmullrom', .3);
  const lookCurve = new CatmullRomCurve3([
    new Vector3(0, 0, .25), new Vector3(-.5, 0, -.1),
    new Vector3(1, 0, 0), new Vector3(.2, 0, -.2),
    new Vector3(-.4, 0, .7)
  ], false, 'catmullrom', .3);
  const reviewCamera = new Vector3(6.5, 13.8, 13);
  const reviewLook = new Vector3(0, 0, 1);
  const smooth = (a, b, x) => {
    const p = Math.max(0, Math.min(1, (x - a) / (b - a)));
    return p * p * (3 - 2 * p);
  };

  const risk = surface.querySelector('.terminal-plan');
  const chartView=surface.querySelector('.terminal-chart-view');
  const levels={target:risk.querySelector('.terminal-tp'),entry:risk.querySelector('.terminal-entry'),stop:risk.querySelector('.terminal-sl')};
  const profit=risk.querySelector('.terminal-profit-fill'),loss=risk.querySelector('.terminal-loss-fill');
  let chartStep=-1;
  const intelligence = surface.querySelector('.terminal-analysis');
  const journal = surface.querySelector('.terminal-review');
  // The journal slides from underneath the console, as in the original scene.
  surface.append(journal);
  const viewport = new Matrix4(), plane = new Matrix4();
  const model = new Matrix4(), projected = new Matrix4();
  let progress = 0, target = 0, active = true, paused = staticView;
  let still = staticView, mobile = false, frame = 0, last = 0;
  let pixelsPerDepthUnit = 1, pixelsPerHeightUnit = 1;

  function draw(time) {
    frame = 0;
    if (document.hidden || !active) return;
    const dt = last ? Math.min(64, time - last) : 16;
    last = time;
    progress = still ? target : progress + (target - progress) * (1 - Math.exp(-dt / 80));
    if (Math.abs(target - progress) < .0003) progress = target;

    const p = progress;
    const loc = curve.getPoint(p), look = lookCurve.getPoint(p);
    const reviewFocus = smooth(.72, .84, p);
    loc.lerp(reviewCamera, reviewFocus);
    look.lerp(reviewLook, reviewFocus);
    if (mobile) {
      loc.set(loc.x * .4, 13.5, 8.5);
      look.set(0, 0, .35);
    }
    camera.position.copy(loc);
    camera.lookAt(look);
    camera.updateMatrixWorld();
    model.makeRotationY(!paused && p < .01 ? Math.sin(time / 3500) * .009 : 0);

    // CSS homogeneous coordinates reproduce the original perspective camera.
    // Only the artwork changes: the camera and scroll-to-time mapping do not.
    projected.copy(viewport).multiply(camera.projectionMatrix)
      .multiply(camera.matrixWorldInverse).multiply(model).multiply(plane);
    const denominator = projected.elements[15];
    surface.style.transform = `matrix3d(${projected.elements.map(v => v / denominator).join(',')})`;

    // Preserve the original camera; expand the chart's range to reveal the plan.
    const expansion=Math.round(smooth(.40,.60,p)*80)/80;
    if(expansion!==chartStep){
      chartStep=expansion;
      chartView.innerHTML=heroChartHTML(expansion);
      const scale=heroChartState(expansion);
      for(const [key,level] of Object.entries(levels))level.style.top=`${scale[key]}%`;
      profit.style.top=`${scale.target}%`;profit.style.height=`${scale.entry-scale.target}%`;
      loss.style.top=`${scale.entry}%`;loss.style.height=`${scale.stop-scale.entry}%`;
    }
    const reveal = smooth(.46, .60, p);
    // Reveal horizontally: vertical scaling would detach labels from their prices.
    risk.style.clipPath = `inset(0 ${(1-reveal)*100}% 0 0)`;
    risk.style.opacity = reveal;
    intelligence.style.transform = `translateZ(${(.03 + .12 * smooth(.28, .48, p)) * pixelsPerHeightUnit}px)`;
    const reviewReveal = smooth(.7, .82, p);
    const journalOffset = -1.3 * (1 - reviewReveal) * pixelsPerDepthUnit;
    const journalScale = .75 + .25 * reviewReveal;
    journal.style.transform = `translateY(${journalOffset}px) translateZ(-2px) scale(${journalScale})`;
    // Explicitly occlude the portion still inside the console. This preserves
    // the original drawer reveal even when browser masks flatten a 3D layer.
    journal.style.clipPath = `inset(${Math.max(0, (-8 - journalOffset) / journalScale)}px 0 0 0)`;
    surface.dataset.phase = ['arrive', 'understand', 'interpret', 'plan', 'review'][Math.min(4, Math.floor(p * 5))];
    if (Math.abs(target - progress) > .0003 || (!paused && p < .01)) frame = requestAnimationFrame(draw);
  }

  function request() {
    if (!frame) frame = requestAnimationFrame(draw);
  }
  function resize() {
    const { width, height } = wrap.getBoundingClientRect();
    if (!width || !height) return;
    mobile = innerWidth <= 700;
    const screenWidth = surface.offsetWidth, screenHeight = surface.offsetHeight;
    pixelsPerDepthUnit = screenHeight / 5.6;
    pixelsPerHeightUnit = screenWidth / 9.1;
    // DOM x/y are the world console's x/z; local positive z lifts a panel.
    plane.set(9.1 / screenWidth, 0, 0, -4.55,
      0, 0, 9.1 / screenWidth, .168,
      0, 5.6 / screenHeight, 0, -2.8,
      0, 0, 0, 1);
    viewport.set(width / 2, 0, 0, width / 2,
      0, -height / 2, 0, height / 2,
      0, 0, 1, 0,
      0, 0, 0, 1);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    request();
  }
  new ResizeObserver(resize).observe(wrap);
  document.addEventListener('academy:journey', e => {
    still = Boolean(e.detail.static);
    paused = still || e.detail.paused;
    target = still ? e.detail.progress : paused ? progress : e.detail.progress;
    active = e.detail.active;
    request();
  });
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) request();
  });
  resize();
  wrap.classList.add('scene-ready');
  ready();
  request();
}
