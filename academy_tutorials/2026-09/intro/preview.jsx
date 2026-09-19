// Native Higgsedit direction preview. Genuine, sanitized UI crops only.
import fs from 'node:fs/promises';
const ROOT='/home/user/academy-intro';
export default async ({project})=>{
 const p=await project({dir:ROOT+'/project',size:'1920x1080',fps:30,background:'#060907'});
 const bold=await p.add('/usr/share/fonts/truetype/higgsfield/Metropolis-ExtraBold.ttf');
 const regular=await p.add('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf');
 const images={};
 for(const key of ['1-0','5-2','5-0','6-0']) images[key]=await p.add(ROOT+'/input/assets/'+key+'-asset.jpg');
 const C={lime:'#c1f28b',white:'#f2f4ec',muted:'#abb8a6',line:'#35432e',black:'#060907'};
 const fade=(dur,delay=0)=>[{property:'opacity',keyframes:[{at:0,value:0},{at:Math.max(.001,delay),value:0},{at:delay+.7,value:1},{at:dur-.6,value:1},{at:dur-.03,value:0}],easing:'ease-in-out'}];
 const move=(dur,delay=0)=>[...fade(dur,delay),{property:'offsetY',from:28,to:0,at:delay,duration:1.1,easing:'house'}];
 const T=(s,x,y,w,h,size=70,color=C.white,strong=true,extra={})=><text x={x} y={y} width={w} height={h} fontSize={size} lineHeight={1.13} color={color} typography={{fontAssetId:strong?bold.id:regular.id}} {...extra}>{s}</text>;
 const tx=(s,y,size=125,color=C.white,w=1696)=>T(s,112,y,w,Math.ceil(size*2.7),size,color);
 const scene=(nodes,at,dur,name)=>p.compose(nodes,{at,dur,name});
 const label=(n,txt)=>T(n+'  /  '+txt,112,125,1650,50,27,C.lime,false,{letterSpacing:3});
 const ui=(key,x,y,w,h,dur,delay=.6)=>{
  const a=images[key],r=Math.min(w/a.width,h/a.height),iw=a.width*r,ih=a.height*r;
  return <group animate={[...fade(dur,delay),{property:'scale',from:.96,to:1,at:delay,duration:1.5,easing:'house'}]}>
   <rect x={x+(w-iw)/2-18} y={y+(h-ih)/2-18} width={iw+36} height={ih+36} radius={24} fill='#141d15' strokeColor='#3a4c34' strokeWidth={2} shadow={{x:0,y:16,blur:40,color:'#00000099'}}/>
   <media file={a} x={x+(w-iw)/2} y={y+(h-ih)/2} width={iw} height={ih} fit='contain'/>
  </group>;
 };
 scene([
  <rect width={1920} height={1080} fill={C.black}/>,
  <rect x={480} y={-260} width={1850} height={1500} fill={{kind:'radial',stops:[{offset:0,color:'#243d1c',opacity:.6},{offset:.65,color:'#0a1109',opacity:.2},{offset:1,color:C.black,opacity:0}]}}/>,
  <rect x={112} y={65} width={40} height={4} fill={C.lime}/>,T('PRO TRADER ACADEMY',172,51,900,46,26,C.muted,false,{letterSpacing:3}),
  T('DIRECTION PREVIEW',1430,51,380,42,21,C.muted,false,{align:'right'}),
  <rect x={112} y={1003} width={1696} height={1} fill='#273022'/>,
  T('EDUCATIONAL ONLY  /  NOT FINANCIAL ADVICE',112,1020,1250,40,20,C.muted,false,{letterSpacing:2})
 ],0,84,'Atmosphere and brand');
 scene([
  <path x={112} y={256} width={1696} height={280} d='M 0 236 C 180 236 260 216 410 216 C 610 216 650 65 840 65 C 1080 65 1140 122 1330 122 C 1480 122 1550 30 1696 30' stroke={{width:3,color:'#516b42',cap:'round'}} mask={{width:1,height:280}} animate={[{property:'maskWidth',from:0,to:1696,at:.15,duration:2.4,easing:'ease-in-out'},...fade(8)]}/>,
  <group animate={move(8,.35)}>{tx('Clarity',334,170)}{tx('starts here.',520,170,C.lime)}
   {T('Your introduction to the Academy + PROTrader.',120,758,1570,80,39,C.muted,false)}
  </group>
 ],0,8,'01 Clarity');
 scene([
  label('01','YOUR LEARNING ECOSYSTEM'),
  <group animate={move(10,.1)}>{T('Learn.',112,244,860,160,138)}{T('Explore.',112,411,860,160,138,C.lime)}{T('Practise.',112,578,860,160,138)}</group>,
  ui('1-0',970,262,805,495,10,.65),
  T('PROTrader · Your analysis workspace',986,810,810,80,32,C.muted,false,{animate:fade(10,1.1)}),
  T('Foundations. Guided lessons. Instructor support.',112,895,1690,65,37,C.muted,false,{animate:fade(10,.8)})
 ],8,10,'02 Learn explore practise');
 scene([
  label('02','ARIA'),
  <group animate={move(12,.1)}>{T('Understand\nthe reasoning.',112,281,780,380,112)}{T('Including when to wait.',116,720,770,104,43,C.lime,false)}</group>,
  ui('5-2',1040,231,705,505,12,.6),ui('5-0',1040,793,705,110,12,3),
  T('ILLUSTRATIVE DEMO',1040,184,690,44,23,C.muted,false)
 ],18,12,'03 ARIA');
 const markers=Array.from({length:9},(_,i)=><rect x={113+i*100} y={675} width={75} height={14} radius={7} fill={i<8?C.lime:'#364032'} animate={fade(13,.8+i*.09)}/>);
 scene([
  label('03','ORACLE'),
  T('8 / 9',103,273,980,296,220,C.lime,true,{animate:move(13,.2)}),
  T('matching checks',115,559,900,99,68,C.white,true,{animate:move(13,.5)}),...markers,
  T('About 89% confluence',115,740,980,86,46,C.muted,false,{animate:fade(13,1.9)}),
  ui('6-0',1165,245,596,471,13,1.2),
  T('Separate illustrative example',1158,769,665,62,28,C.muted,false),
  T('Matching checks—not win probability.',112,900,1690,65,45,C.white,false,{animate:fade(13,4)})
 ],30,13,'04 The same checks in one view');
 scene([
  label('04','YOU STAY IN CONTROL'),
  <group animate={move(9,.15)}>{tx('Compare.',262,140)}{tx('Question.',431,140,C.lime)}{tx('Decide.',600,140)}</group>,
  T('The tools support your review.',117,840,1660,100,44,C.muted,false,{animate:fade(9,.7)})
 ],43,9,'05 Human judgement');
 const cards=[['01','Follow a lesson','Build understanding'],['02','Save your notes','Record your reasoning'],['03','Ask your instructor','Learn through feedback']];
 scene([
  label('05','YOUR ACADEMY'),
  tx('Put learning into practice.',260,106),
  ...cards.map((c,i)=><group animate={move(13,.6+i*.3)}>
   <rect x={112+i*576} y={500} width={542} height={361} radius={25} fill='#111910' strokeColor={C.line} strokeWidth={2}/>
   {T(c[0],144+i*576,538,446,100,66,C.lime)}
   {T(c[1],144+i*576,679,460,85,40,C.white)}
   {T(c[2],144+i*576,776,460,61,26,C.muted,false)}
  </group>),
  T('Illustrated learning path · Feedback comes from your instructor.',112,922,1696,48,27,C.muted,false)
 ],52,13,'06 Learning loop — illustrative graphic');
 scene([
  label('06','YOUR FIRST STEP'),
  <group animate={move(10,.1)}>{tx('Start here.',263,153,C.lime)}{tx('Then go deeper.',467,117)}</group>,
  T('The basics',114,730,455,90,51,C.white,true,{animate:fade(10,.6)}),T('→',696,730,120,100,60,C.lime,false,{animate:fade(10,1)}),
  T('Feature guides',1020,730,710,100,51,C.white,true,{animate:fade(10,1.2)}),
  T('Charts · tickets · journaling · analysis',1020,832,743,70,30,C.muted,false,{animate:fade(10,1.3)})
 ],65,10,'07 Start here then features');
 scene([
  <group animate={move(9,.2)}>{T('PRO TRADER',112,260,1696,188,155,C.white,true,{align:'center'})}{T('ACADEMY',112,459,1696,168,139,C.lime,true,{align:'center'})}
   {T('Understand the tools. Build your process.',112,688,1696,89,43,C.muted,false,{align:'center'})}
   <rect x={704} y={824} width={512} height={88} radius={44} fill={C.lime}/>{T('Begin the basics',704,843,512,60,34,'#10190b',true,{align:'center'})}
  </group>
 ],75,9,'08 Begin the basics');
 await fs.mkdir(ROOT+'/frames',{recursive:true});
 for(const [i,t] of [3,12,23,36,47,59,70,80].entries())await p.frame(t,ROOT+`/frames/scene-${i}.png`);
 console.log('BUILT',p.duration());
};
