const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const html=fs.readFileSync(path.join(__dirname,'../protrader_mobile.html'),'utf8');
function section(a,b){const start=html.indexOf(a),end=html.indexOf(b,start);assert.ok(start>=0&&end>start,a);return html.slice(start,end);}
function harness(){
  const pane={innerHTML:''},S={sym:'R_50',tf:'15m',candles:[],activePatterns:[],newsWeek:false};
  const context=vm.createContext({S,ariaHistoryStatus:()=>({available:true}),document:{getElementById:()=>pane},requestChartRedraw:()=>{},calcEMA:(items,period)=>Array(items.length).fill(period===20?190:180)});
  vm.runInContext(section('const ARIA_GATE_COUNT =','function renderARIA()')+section('const PATTERNS = [','/* ════════════════════════════════════════════════════════════\n   MTF CONFLUENCE')+'\nglobalThis.detectors=PATTERNS;globalThis.setDetectors=value=>PATTERNS.splice(0,PATTERNS.length,...value);',context);
  context.checkModel=()=>{const closes=S.candles.map(c=>c.close);return{gates:{dir:context.ariaDirection(closes,context.calcEMA(closes,20),context.calcEMA(closes,50))}};};
  return{context,pane,S};
}
function candles(n=40){return Array.from({length:n},(_,i)=>({time:1800000000+i*900,open:99,high:101,low:98,close:100}));}

test('actual Double Top and Double Bottom cannot pass by rediscovering an old completion',()=>{
  for(const [name,dir] of [['Double Top','sell'],['Double Bottom','buy']]){
    const h=harness(),detector=h.context.detectors.find(p=>p.name===name);h.context.setDetectors([detector]);
    for(const [peaks,expected] of [[[27,28,30],null],[[33,34,36],null],[[34,35,37],name]]){
      const bars=candles();for(const i of peaks)bars[i].high=110;
      if(dir==='buy')for(const b of bars){const old={...b};b.open=220-old.open;b.close=220-old.close;b.high=220-old.low;b.low=220-old.high;}
      const detected=detector.detect(bars,37);assert.equal(detected.i,peaks.at(-1));assert.ok(detected.conf>=75);
      assert.equal(h.context.getPatternAlignment(dir,bars),expected,`${name}: completion ${peaks.at(-1)}`);
    }
  }
});

test('scanner badge qualifies the displayed occurrence rather than another occurrence with the same name',()=>{
  const h=harness();h.S.candles=candles(100).map(b=>({...b,open:199,high:201,low:198,close:200}));
  const repeated={name:'Repeated pattern',dir:'bull',detect:(_bars,i)=>i===70?{i,start:69,conf:95}:i===99?{i,start:98,conf:80}:null};
  h.context.setDetectors([repeated]);assert.equal(h.context.getPatternAlignment('buy',h.S.candles),'Repeated pattern');
  h.context.runPatternScanner();assert.match(h.pane.innerHTML,/Fit 95\/100/);assert.doesNotMatch(h.pane.innerHTML,/✓ ARIA/);
  h.context.setDetectors([{...repeated,detect:(_bars,i)=>i===99?{i,start:98,conf:80}:null}]);
  h.context.runPatternScanner();assert.match(h.pane.innerHTML,/✓ ARIA/);
  h.context.calcEMA=(items,period)=>Array(items.length).fill(period===20?200:180);
  h.context.runPatternScanner();assert.doesNotMatch(h.pane.innerHTML,/✓ ARIA/,'Equal or mixed stacks are neutral in scanner and Check');
  h.context.checkModel=()=>({unavailableReason:'Stale or unverified history'});
  h.context.runPatternScanner();assert.doesNotMatch(h.pane.innerHTML,/✓ ARIA/,'Unavailable Check evidence cannot endorse a scanner occurrence');
});

test('pattern completion must be explicit and within the current history',()=>{
  const h=harness();
  for(const i of [undefined,null,NaN,37.5,36,40])assert.equal(h.context.ariaPatternQualifies({i,conf:90},'buy','bull',40),false);
  assert.equal(h.context.ariaPatternQualifies({i:37,conf:75},'buy','bull',40),true);
  assert.equal(h.context.ariaPatternQualifies({i:39,conf:74},'buy','bull',40),false);
  assert.equal(h.context.ariaPatternQualifies({i:39,conf:90},'neutral','bear',40),false);
});

test('MCC preserves existing boundaries and blocks while naming the strategy honestly',()=>{
  const h=harness(),bars=candles(30).map(b=>({...b,open:100,high:110,low:90,close:100}));bars[29]={time:1800000000,open:100,high:105,low:95,close:99};
  const inputs=[bars,bars.map(b=>b.close),Array(30).fill(98),Array(30).fill(97),Array(30).fill(1)];
  const at=hour=>Date.UTC(2026,9,19,hour)/1000;
  const rejection=h.context.ariaMCC(...inputs,at(12));assert.equal(rejection.code,'FAKE_BREAK');assert.equal(rejection.label,'Closing-price rejection');
  assert.match(rejection.desc,/prior 14 closing prices/);assert.doesNotMatch(rejection.desc,/Reduce size|Expect mean reversion|False break detected/);
  const restriction=h.context.ariaMCC(...inputs,at(3));assert.equal(restriction.code,'DEAD_ZONE');assert.match(restriction.desc,/strategy.*every instrument/);
  assert.doesNotMatch(restriction.desc,/70%|fake moves/);
  for(const mcc of [rejection,restriction])assert.equal(h.context.ariaVerdict(10,mcc,'R_50','buy',h.S,{available:true,unavailable:0}).v,'OBSERVER');
});
