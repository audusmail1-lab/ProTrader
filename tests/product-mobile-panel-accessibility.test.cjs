const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const html=fs.readFileSync(path.join(__dirname,'../protrader_mobile.html'),'utf8');
function harness(){
 const classes=()=>{const set=new Set();return{contains:k=>set.has(k),add:k=>set.add(k),remove:k=>set.delete(k),toggle(k,on){const yes=on??!set.has(k);yes?set.add(k):set.delete(k);return yes;}};};
 const elements={},body={classList:classes()},doc={body,activeElement:null,getElementById:id=>elements[id],querySelector:selector=>selector.includes('mobile-nav-btn')?elements.workspace:selector==='.rtab.active'?elements.tab:null,querySelectorAll:()=>[]};
 const node=id=>{const el={id,isConnected:true,classList:classes(),attrs:{},inert:false,dataset:{},setAttribute(k,v){this.attrs[k]=v;},removeAttribute(k){delete this.attrs[k];},getClientRects:()=>[{}],closest:()=>null,focus(){doc.activeElement=this;},blur(){doc.activeElement=null;}};elements[id]=el;return el;};
 const panel=node('rightPanel'),tab=node('tab'),learn=node('learn'),opener=node('opener'),outside=node('outside'),workspace=node('workspace'),toggle=node('wsTogAnalysis');
 panel.contains=el=>el===tab||el===learn||el===panel;panel.querySelector=()=>tab;tab.dataset.tab='check';doc.activeElement=opener;
 const c=vm.createContext({document:doc,isMobile:()=>c.mobile,mobile:true,setRTab:tabName=>{tab.dataset.tab=tabName;},window:{}});
 vm.runInContext(html.slice(html.indexOf('function syncRightPanelAccessibility()'),html.indexOf('function mobileSetView(view)')),c);
 return{c,doc,panel,tab,learn,opener,outside,workspace,toggle};
}
test('closed mobile panel is inert and removed from the accessibility tree',()=>{
 const h=harness();h.c.syncRightPanelAccessibility();assert.equal(h.panel.inert,true);assert.equal(h.panel.attrs['aria-hidden'],'true');assert.equal(h.doc.activeElement,h.opener);
});
test('opening a mobile tab restores its controls and focuses the selected tab; closing restores the opener',()=>{
 const h=harness();h.c.syncRightPanelAccessibility();h.c.openMobilePanel('oracle');
 assert.equal(h.panel.inert,false);assert.equal(h.panel.attrs['aria-hidden'],undefined);assert.equal(h.doc.activeElement,h.tab);assert.equal(h.tab.dataset.tab,'oracle');
 h.learn.focus();h.c.closeMobilePanel();assert.equal(h.panel.inert,true);assert.equal(h.doc.activeElement,h.opener);
});
test('closing never steals focus from another visible control and falls back when the opener disappears',()=>{
 const h=harness();h.c.openMobilePanel('check');h.outside.focus();h.c.closeMobilePanel();assert.equal(h.doc.activeElement,h.outside);
 h.opener.focus();h.c.openMobilePanel('check');h.opener.isConnected=false;h.c.closeMobilePanel();assert.equal(h.doc.activeElement,h.workspace);
});
test('desktop visibility is independent of mobile open state and follows the desktop analysis toggle',()=>{
 const h=harness();h.c.syncRightPanelAccessibility();h.c.mobile=false;h.c.syncRightPanelAccessibility();assert.equal(h.panel.inert,false);assert.equal(h.panel.attrs['aria-hidden'],undefined);
 h.learn.focus();h.doc.body.classList.add('ws-analysis-off');h.c.syncRightPanelAccessibility();assert.equal(h.panel.inert,true);assert.equal(h.doc.activeElement,h.toggle);
 h.doc.body.classList.remove('ws-analysis-off');h.c.syncRightPanelAccessibility();assert.equal(h.panel.inert,false);
 assert.match(html,/window\.matchMedia\(MOBILE_MQ\)\.addEventListener\?\.\('change',syncRightPanelAccessibility\)/);
 const workspace=html.slice(html.indexOf('const WS ='),html.indexOf('  toggle(k)',html.indexOf('const WS =')));assert.equal((workspace.match(/syncRightPanelAccessibility\(\)/g)||[]).length,2);
});
test('Practice and Replay identify the deterministic check separately from the Oracle agent, retaining the existing engine',()=>{
 const practice=html.slice(html.indexOf('  panel_practice()'),html.indexOf('  setPlan(k, val)',html.indexOf('  panel_practice()')));
 const replay=html.slice(html.indexOf('const REPLAY ='),html.indexOf('const CTX ='));
 assert.match(practice,/>Practice rules check<\/button>/);assert.match(practice,/process score, not win probability/);assert.doesNotMatch(practice,/Check with ORACLE|Overrode ORACLE/);
 assert.match(replay,/>Practice rules check<\/button>/);assert.match(replay,/plan\.check = ORACLE\.check\(/);
 const source=html.slice(html.indexOf('const ORACLE ='),html.indexOf('\n\n\n/*',html.indexOf('const ORACLE =')));
 const c=vm.createContext({});vm.runInContext(source+';globalThis.check=ORACLE.check;',c);
 assert.equal(c.check({side:'buy',entry:100},null,null).status,'INCOMPLETE');
 const read={atr:2,structure:{trend:'up',lastBreak:null,lowBelow:{price:97,type:'low',time:1700000000},highAbove:null},zones:[],near:{above:null,below:null}};
 const valid={side:'buy',entry:100,stop:96,target:108};assert.equal(c.check(valid,read,null).status,'SUPPORTED');assert.equal(c.check({...valid,stop:101},read,null).status,'CONTRADICTED');
});
