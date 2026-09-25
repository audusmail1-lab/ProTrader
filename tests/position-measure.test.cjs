const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync(require('node:path').join(__dirname, '../protrader_mobile.html'), 'utf8');
const source = html.slice(html.indexOf('const DRAW_COLORS'), html.indexOf('// ATR cache kept'));

function setup() {
  const events = {}, storage = {};
  const element = name => ({style:{}, clientWidth:800, clientHeight:600,
    getBoundingClientRect:()=>({left:0,top:0}),
    addEventListener:(type,fn)=>{(events[name+type] ||= []).push(fn);},
    setPointerCapture(){},hasPointerCapture(){return false;},releasePointerCapture(){}});
  const wrap=element('wrap'),il=element('il');
  const context = vm.createContext({
    S:{sym:'TEST',tf:'1m',dp:2},TF_SEC:{'1m':60},
    CH:{toX:t=>t,toY:p=>500-p*4,fromX:x=>x,fromY:y=>(500-y)/4,syncOverlay(){}},
    LIVE:{routing:()=>false,acct:()=>({currency:'USD'}),specLimits:()=>null,riskAtStop:()=>null},
    otSpec:()=>({lotStep:.01,minLot:.01,maxLot:100}),otPnl:(side,e,s,v)=> (s-e)*100*v,
    document:{activeElement:null,getElementById:id=>id==='chartWrap'?wrap:id==='interactLayer'?il:null,
      querySelectorAll:()=>[],addEventListener:(type,fn)=>{(events['doc'+type] ||= []).push(fn);}},
    window:{addEventListener:(type,fn)=>{(events['win'+type] ||= []).push(fn);}},
    localStorage:{getItem:key=>storage[key],setItem:(key,v)=>{storage[key]=v;}}
  });
  vm.runInContext(source+';globalThis.draw=DRAW;globalThis.arm=setDraw;',context);
  const d=context.draw; d.chip=()=>{};
  const fire=(name,x,y,id=1)=>{for(const fn of events[name]||[]) fn({clientX:x,clientY:y,pointerId:id,button:0,
    type:name.replace(/^(wrap|win|doc)/,''),target:{closest:()=>null},preventDefault(){},stopPropagation(){}});};
  return {context,d,fire};
}
const marker=type=>({id:1,type,riskBudget:100,pts:[{t:100,p:100},{t:300,p:type==='long'?90:110},
  {t:300,p:type==='long'?120:80},{t:300,p:100}]});

test('inline application JavaScript parses',()=>{
  for(const script of html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)) new vm.Script(script[1]);
});
for(const type of ['long','short']) {
  test(`${type}: signed zones, risk budget sizing, reward and ratio`,()=>{
    const {d}=setup(),m=marker(type),s=d.positionStats(m);
    assert.equal(s.ratio,2);assert.equal(s.lots,.1);assert.equal(s.risk,100);assert.equal(s.reward,200);
    d.resizePosition(m,1,{t:0,p:type==='long'?80:120});
    assert.equal(m.pts[0].p,100);assert.equal(m.pts[2].p,type==='long'?120:80);
    assert.equal(d.positionStats(m).lots,.05);assert.equal(d.positionStats(m).ratio,1);
  });
  test(`${type}: stops and targets cannot cross entry; entry stays between levels`,()=>{
    const {d}=setup(),m=marker(type),sign=type==='long'?1:-1;
    d.resizePosition(m,1,{p:100+sign*50});d.resizePosition(m,2,{p:100-sign*50});
    assert.ok(sign*(m.pts[0].p-m.pts[1].p)>0);assert.ok(sign*(m.pts[2].p-m.pts[0].p)>0);
    const n=marker(type);d.resizePosition(n,0,{p:1000});
    assert.ok(n.pts[0].p<Math.max(n.pts[1].p,n.pts[2].p));assert.equal(n.pts[3].p,n.pts[0].p);
  });
}
test('rounds size down to lot step, respects min/max and missing conversion',()=>{
  const {d,context}=setup(),m=marker('long');m.riskBudget=109;
  assert.equal(d.positionStats(m).lots,.1);
  m.riskBudget=.1;assert.equal(d.positionStats(m).lots,0);
  m.riskBudget=1e9;assert.equal(d.positionStats(m).lots,100);
  context.otPnl=()=>null;assert.equal(d.positionStats(m).lots,null);
  context.LIVE.routing=()=>true;context.LIVE.riskAtStop=()=>1000;
  assert.equal(d.positionStats(m).lots,null,'wrong/missing broker symbol must not use paper sizing');
});
test('width dragging keeps all prices unchanged',()=>{
  const {d}=setup(),m=marker('long');d.resizePosition(m,3,{t:500,p:5});
  assert.deepEqual(m.pts.map(p=>p.p),[100,90,120,100]);assert.equal(m.pts[2].t,500);
});
test('pointer drag modifies SL independently and persists per symbol',()=>{
  const {d,fire,context}=setup(),m=marker('long');d.list().push(m);d.sel=1;
  fire('wrappointerdown',200,140);fire('winpointermove',200,180);fire('winpointerup',200,180);
  assert.equal(m.pts[1].p,80);assert.equal(m.pts[0].p,100);assert.equal(m.pts[2].p,120);
  d.bySym={};d.load();assert.equal(d.list()[0].pts[1].p,80);
  context.S.sym='OTHER';assert.equal(d.list().length,0);
});
test('cancel and symbol switch restore a drag; other pointers cannot move it',()=>{
  const {d,fire,context}=setup(),m=marker('long');d.list().push(m);d.sel=1;
  fire('wrappointerdown',200,140);fire('winpointermove',200,200,2);assert.equal(m.pts[1].p,90);
  fire('winpointermove',200,180);fire('winpointercancel',200,180);assert.equal(m.pts[1].p,90);
  fire('wrappointerdown',200,140);fire('winpointermove',200,180);context.S.sym='OTHER';
  fire('winpointerup',200,180);assert.equal(m.pts[1].p,90);assert.equal(d.mode,'idle');
});
test('single tap creates a marker and disarms the tool',()=>{
  const {d,fire,context}=setup();context.arm('short',null);
  fire('wrappointerdown',200,200);fire('winpointerup',200,200);
  assert.equal(d.list().length,1);assert.equal(d.armed,'none');assert.equal(d.list()[0].pts.length,4);
});
test('TP and entry drags update only their intended levels without grab-offset jumps',()=>{
  const {d,fire}=setup(),m=marker('short');d.list().push(m);d.sel=1;
  fire('wrappointerdown',200,183);fire('winpointermove',200,203);fire('winpointerup',200,203);
  assert.equal(m.pts[2].p,75);assert.equal(m.pts[0].p,100);assert.equal(m.pts[1].p,110);
  fire('wrappointerdown',200,100);fire('winpointermove',200,120);fire('winpointerup',200,120);
  assert.equal(m.pts[0].p,95);assert.equal(m.pts[1].p,110);assert.equal(m.pts[2].p,75);
});
test('dragging a zone translates all levels and preserves risk/reward',()=>{
  const {d,fire}=setup(),m=marker('long');d.list().push(m);d.sel=1;
  fire('wrappointerdown',200,60);fire('winpointermove',220,80);fire('winpointerup',220,80);
  assert.equal(m.pts[0].t,120);assert.equal(m.pts[0].p,95);
  assert.equal(d.positionStats(m).ratio,2);
});
test('existing horizontal-line drag still works',()=>{
  const {d,fire}=setup(),m={id:1,type:'hline',pts:[{t:100,p:100}]};d.list().push(m);d.sel=1;
  fire('wrappointerdown',200,100);fire('winpointermove',200,140);fire('winpointerup',200,140);
  assert.equal(m.pts[0].p,90);
});
