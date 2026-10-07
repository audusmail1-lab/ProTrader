import test from 'node:test';
import assert from 'node:assert/strict';
import {bars,chartSVG} from '../academy/cinematic/market-example.js';
import {heroChartState,heroChartHTML} from '../academy/cinematic/terminal-preview.js';
import {mountScene} from '../academy/cinematic/scene.js';

const close=(a,b,tolerance=1e-8)=>assert.ok(Math.abs(a-b)<tolerance,`${a} differs from ${b}`);
const candleCount=svg=>[...svg.matchAll(/<g class="candle-(?:up|down)">/g)].length;
const path= (svg,name)=>svg.match(new RegExp(`<path class="${name}" d="([^"]+)"`))[1];
const points=d=>[...d.matchAll(/[ML](-?[\d.]+) (-?[\d.]+)/g)].map(([,x,y])=>[Number(x),Number(y)]);

test('hero uses 44 recent candles without changing the planner default or shared fixture',()=>{
 const before=JSON.stringify(bars);
 assert.equal(candleCount(heroChartHTML()),44);
 assert.equal(candleCount(chartSVG()),76);
 assert.equal(JSON.stringify(bars),before);
 assert.equal(bars.at(-1).close,1.0884);
 assert.match(heroChartHTML(),/>03:00</);
 assert.match(heroChartHTML(),/>07:00</);
 assert.match(heroChartHTML(),/>11:00</);
});

test('focused hero view contains every visible candle including its complete wick',()=>{
 const {low,high}=heroChartState(0);
 for(const bar of bars.slice(-44)){
  assert.ok(bar.low>=low,`wick ${bar.low} below visible minimum ${low}`);
  assert.ok(bar.high<=high,`wick ${bar.high} above visible maximum ${high}`);
 }
});

test('cropping to recent candles preserves EMA history rather than restarting at the crop',()=>{
 for(const [period,name] of [[20,'ema-fast'],[50,'ema-slow']]){
  let value=bars[0].close;
  const alpha=2/(period+1);
  const averages=bars.map((bar,index)=>(value=index?bar.close*alpha+value*(1-alpha):bar.close));
  const state=heroChartState(0),rendered=points(path(heroChartHTML(0),name));
  assert.equal(rendered.length,44);
  for(let i=0;i<44;i++){
   const renderedPrice=state.high-(rendered[i][1]-28)/336*(state.high-state.low);
   close(renderedPrice,averages[32+i]);
  }
 }
});

test('every chart expansion maps TP, entry and SL to their stated prices',()=>{
 for(let frame=0;frame<=80;frame++){
  const state=heroChartState(frame/80);
  for(const [key,price] of [['target',1.0924],['entry',1.0884],['stop',1.0864]]){
   const y=state[key]*4;
   const inferred=state.high-(y-28)/336*(state.high-state.low);
   close(inferred,price);
  }
  const quoteY=Number(path(heroChartHTML(frame/80),'quote-line').match(/^M[\d.]+ ([\d.]+)H/)[1]);
  close(quoteY,state.entry*4);
  assert.ok(state.target<state.entry&&state.entry<state.stop);
 }
 const full=heroChartState(1);
 for(const key of ['target','entry','stop'])assert.ok(full[key]>=7&&full[key]<=91);
});

test('chart expansion is bounded and returns exactly to the focused state',()=>{
 assert.deepEqual(heroChartState(-1),heroChartState(0));
 assert.deepEqual(heroChartState(2),heroChartState(1));
 const first=heroChartHTML(0);
 heroChartHTML(1);
 assert.equal(heroChartHTML(0),first);
});

// Exercise the real scene controller using only its DOM boundary. Rendering and
// physical-device appearance remain browser checks; this catches scheduling and
// price-label regressions when static/reduced-motion chapters are selected.
async function sceneHarness({mobile=false,staticView=false}={},run){
 const prior=new Map(['document','innerWidth','ResizeObserver','requestAnimationFrame'].map(key=>[key,Object.getOwnPropertyDescriptor(globalThis,key)]));
 const listeners=new Map(),frames=new Map();
 let nextFrame=0;
 const node=()=>({style:{},dataset:{}});
 const elements=Object.fromEntries(['.terminal-chart-view','.terminal-analysis','.terminal-review','.terminal-tp','.terminal-entry','.terminal-sl','.terminal-profit-fill','.terminal-loss-fill'].map(key=>[key,node()]));
 const risk=node();risk.querySelector=selector=>elements[selector];elements['.terminal-plan']=risk;
 const surface={...node(),offsetWidth:mobile?780:1140,offsetHeight:mobile?590:690,querySelector:selector=>elements[selector],append(){},parentElement:{getBoundingClientRect:()=>({width:mobile?527:1123,height:mobile?414:729}),classList:{add(){}}}};
 globalThis.document={hidden:false,addEventListener:(name,callback)=>listeners.set(name,callback)};
 globalThis.innerWidth=mobile?390:1440;
 globalThis.ResizeObserver=class{observe(){}};
 globalThis.requestAnimationFrame=callback=>{frames.set(++nextFrame,callback);return nextFrame};
 function draw(time=100){const [id,callback]=frames.entries().next().value??[];assert.ok(callback,'a frame should be scheduled');frames.delete(id);callback(time)}
 function journey(detail){listeners.get('academy:journey')({detail})}
 try{
  let ready=false;
  await mountScene(surface,()=>{ready=true},{staticView});
  assert.equal(ready,true);
  await run({surface,elements,frames,draw,journey});
 }finally{
  for(const [key,descriptor] of prior)if(descriptor)Object.defineProperty(globalThis,key,descriptor);else delete globalThis[key];
 }
}

test('reduced-motion desktop and mobile chapter selection updates once with correct plan levels',async()=>{
 for(const mobile of [false,true])await sceneHarness({mobile,staticView:true},({surface,elements,frames,draw,journey})=>{
  draw();assert.equal(frames.size,0);
  journey({progress:.7,paused:false,static:true,active:true});draw(200);
  assert.equal(surface.dataset.phase,'plan');
  assert.equal(frames.size,0);
  const full=heroChartState(1);
  for(const [key,selector] of [['target','.terminal-tp'],['entry','.terminal-entry'],['stop','.terminal-sl']])close(Number.parseFloat(elements[selector].style.top),full[key]);
  assert.ok(surface.style.transform.startsWith('matrix3d('));
  assert.doesNotMatch(surface.style.transform,/NaN|Infinity/);
  journey({progress:0,paused:false,static:true,active:true});draw(300);
  assert.equal(surface.dataset.phase,'arrive');
  assert.equal(elements['.terminal-chart-view'].innerHTML,heroChartHTML(0));
  assert.equal(frames.size,0);
 });
});

test('hero depth keeps the chassis behind the screen and raised panels in front across the camera journey',async()=>{
 for(const mobile of [false,true])await sceneHarness({mobile,staticView:true},({surface,elements,draw,journey})=>{
  // CSS depth increases toward the viewer, unlike OpenGL projected depth.
  // Check the emitted camera transform rather than a particular matrix value:
  // a reversed depth axis can let the opaque chassis cover the entire screen.
  for(let step=0;step<=20;step++){
   const progress=step/20;
   journey({progress,paused:false,static:true,active:true});draw(100+step*100);
   const matrix=surface.style.transform.slice('matrix3d('.length,-1).split(',').map(Number);
   assert.equal(matrix.length,16);
   assert.ok(matrix.every(Number.isFinite),'camera matrix must be finite');
   const raised=Number(elements['.terminal-analysis'].style.transform.match(/^translateZ\(([-\d.]+)px\)$/)?.[1]);
   assert.ok(raised>0,'analysis panel should lift from the screen');
   for(const [u,v] of [[0,0],[1,0],[.5,.5],[0,1],[1,1]]){
    const x=u*surface.offsetWidth,y=v*surface.offsetHeight;
    const depth=z=>{
     const w=matrix[3]*x+matrix[7]*y+matrix[11]*z+matrix[15];
     assert.ok(w>0,'visible terminal must stay in front of the camera');
     return (matrix[2]*x+matrix[6]*y+matrix[10]*z+matrix[14])/w;
    };
    const rear=depth(-10),screen=depth(0),front=depth(raised);
    const context=`${mobile?'mobile':'desktop'} progress ${progress}, point ${u},${v}`;
    assert.ok(rear<screen,`chassis must stay behind screen: ${context}`);
    assert.ok(screen<front,`raised panel must stay in front of screen: ${context}`);
   }
  }
 });
});

test('pausing the arrival stops the idle animation frame loop',async()=>{
 await sceneHarness({},({frames,draw,journey})=>{
  draw();assert.equal(frames.size,1);
  journey({progress:0,paused:true,static:false,active:true});draw(200);
  assert.equal(frames.size,0);
 });
});

test('partially revealed paper levels keep their price coordinates without vertical scaling',async()=>{
 await sceneHarness({staticView:true},({elements,frames,draw,journey})=>{
  journey({progress:.55,paused:false,static:true,active:true});draw();
  const risk=elements['.terminal-plan'];
  assert.ok(!risk.style.transform||risk.style.transform==='none','risk must not be vertically scaled away from chart prices');
  const clip=Number(risk.style.clipPath.match(/^inset\(0 ([\d.]+)% 0 0\)$/)?.[1]);
  assert.ok(clip>0&&clip<100,'partial reveal should clip horizontally');
  assert.ok(Number(risk.style.opacity)>0&&Number(risk.style.opacity)<1);
  const chart=elements['.terminal-chart-view'].innerHTML;
  const labels=[...chart.matchAll(/<text x="832" y="[\d.]+">([\d.]+)<\/text>/g)].map(match=>Number(match[1]));
  assert.equal(labels.length,6);
  const high=labels[0],low=labels.at(-1);
  for(const [selector,price] of [['.terminal-tp',1.0924],['.terminal-entry',1.0884],['.terminal-sl',1.0864]]){
   const y=Number.parseFloat(elements[selector].style.top)*4;
   // The emitted axis labels have five decimals; allow their rounding while
   // checking the actual chart against the independently displayed price levels.
   close(high-(y-28)/336*(high-low),price,.00001);
  }
  const quoteY=Number(path(chart,'quote-line').match(/^M[\d.]+ ([\d.]+)H/)[1]);
  close(quoteY,Number.parseFloat(elements['.terminal-entry'].style.top)*4);
  assert.equal(frames.size,0);
  journey({progress:.60,paused:false,static:true,active:true});draw(200);
  assert.equal(risk.style.clipPath,'inset(0 0% 0 0)');
  assert.equal(Number(risk.style.opacity),1,'all paper levels must be visible at the Plan chapter stop');
  assert.equal(frames.size,0);
 });
});
