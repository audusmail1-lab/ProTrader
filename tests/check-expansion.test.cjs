const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const html=fs.readFileSync(require('node:path').join(__dirname,'../protrader_mobile.html'),'utf8');
test('check expansion survives repeated market renders and closes only on toggle',()=>{
  const panel={innerHTML:''},button={setAttribute(){},focus(){},textContent:''};
  const context=vm.createContext({document:{activeElement:null,getElementById:id=>({
    'check-panel':panel,chkMoreToggle:button,chkMore:{classList:{toggle(){}}}
  }[id])},S:{dp:5,sym:'EURUSD',symLabel:'EUR/USD',tf:'15m',balance:10000,riskPct:1},
  CHECK_TERMS:{},LIVE:{routing:()=>false},otMoney:n=>n.toFixed(2),otPnl:()=>100,
  riskLots:()=>({lots:.1,min:.01}),otSpec:()=>({isForex:true,pip:.0001}),
  checkModel:()=>({gates:{dir:'buy',score:7,gates:Array.from({length:9},(_,i)=>({name:'gate'+i,detail:'Updated',pass:i<7}))},
    verdict:{v:'QUALIFIED',msg:'Ready'},entry:{entry:1.1,slLevel:1.09,tp2:1.12},mcc:{code:'TREND',label:'Trend'},oracle:78,
    session:{label:'London'},wyck:{phase:'MARKUP'},patternAlign:''})});
  vm.runInContext(html.slice(html.indexOf('const CHECK_UI'),html.indexOf('function reviewFromCheck')),context);
  context.renderCheck();assert.match(panel.innerHTML,/aria-expanded="false"/);
  context.toggleMoreChecks();
  for(let i=0;i<10;i++) context.renderCheck();
  assert.match(panel.innerHTML,/class="chk-more open"/);assert.match(panel.innerHTML,/aria-expanded="true"/);
  context.toggleMoreChecks();context.renderCheck();assert.match(panel.innerHTML,/aria-expanded="false"/);
});
