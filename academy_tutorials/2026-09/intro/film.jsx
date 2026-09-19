// Original Academy film. Native typography/motion; genuine, sanitised product images.
import fs from 'node:fs/promises';
const ROOT='/home/user/academy-film';
export default async ({project})=>{
 const timing=JSON.parse(await fs.readFile(ROOT+'/timing.json','utf8'));
 const D=timing.duration;
 for(const format of (process.env.FILM_FORMAT?[process.env.FILM_FORMAT]:['landscape','portrait'])){
  const mobile=format==='portrait', W=mobile?1080:1920,H=mobile?1920:1080,M=mobile?76:104;
  const p=await project({dir:ROOT+'/project-'+format,size:`${W}x${H}`,fps:30,background:'#070b08'});
  const bold=await p.add('/usr/share/fonts/truetype/higgsfield/Metropolis-ExtraBold.ttf');
  const regular=await p.add('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf');
  const files={chart:'assets/chart.png',notes:'assets/notes.png',saved:'assets/notes-saved.png',question:'assets/question.jpg',aria:'input/assets/5-2-asset.jpg',wait:'input/assets/5-0-asset.jpg',oracle:'input/assets/6-0-asset.jpg'};
  const assets={};for(const [k,f] of Object.entries(files))assets[k]=await p.add(ROOT+'/'+f);
  const ink='#070b08',lime='#c1f28b',white='#f2f4ec',muted='#aab8a5';
  const fade=d=>[{property:'opacity',keyframes:[{at:0,value:0},{at:.28,value:1},{at:d-.3,value:1},{at:d-.02,value:0}]}];
  const enter=(at=0,d=.55)=>[{property:'opacity',from:0,to:1,at,duration:d,easing:'ease-in-out'}];
  const words={by:'word',from:{y:22,opacity:0},at:.1,duration:.55,overlap:.8,easing:'house'};
  const T=(s,x,y,w,h,size=100,color=white,strong=true,extra={})=><text x={x} y={y} width={w} height={h} fontSize={size} color={color} lineHeight={1.12} typography={{fontAssetId:strong?bold.id:regular.id}} {...extra}>{s}</text>;
  const shots=[];
  const scene=(nodes,at,dur,name)=>{p.compose(<group animate={fade(dur)}>{nodes}</group>,{at,dur,name});shots.push({at,dur,name});};
  const ui=(key,x,y,w,h,label)=>[
   <rect x={x-16} y={y-16} width={w+32} height={h+32} radius={24} fill='#111a0e' strokeColor='#42513a' strokeWidth={2}/>,
   <media file={assets[key]} x={x} y={y} width={w} height={h} fit='contain'/>,
   ...(label?[T(label,x,y+h+34,w,70,mobile?32:28,muted,false)]:[])
  ];
  const base=[
   <rect width={W} height={H} fill={ink}/>,
   <rect x={mobile?-340:340} y={-470} width={2140} height={2050} fill={{kind:'radial',stops:[{offset:0,color:'#29451c',opacity:.65},{offset:.78,color:ink,opacity:0}]}}/>,
   <rect x={M} y={mobile?76:60} width={30} height={4} fill={lime}/>,
   T('PRO TRADER ACADEMY',M+50,mobile?61:45,W-2*M-50,52,mobile?28:26,muted,false,{letterSpacing:2}),
   <rect x={M} y={H-94} width={W-2*M} height={1} fill='#34412d'/>,
   T('Educational only · Not financial advice',M,H-74,W-2*M,51,mobile?27:26,muted,false),
   <rect x={M} y={H-95} width={W-2*M} height={2} fill={lime} mask={{width:1,height:2}} animate={[{property:'maskWidth',from:1,to:W-2*M,duration:D,easing:'linear'}]}/>
  ];
  p.compose(base,{at:0,dur:D,name:'Academy identity and disclosure'});
  scene([
   <path x={M} y={mobile?490:270} width={W-2*M} height={300} d='M 0 245 C 210 245 270 190 405 190 C 620 190 674 65 860 65 C 1110 65 1180 145 1340 145 C 1530 145 1600 25 1712 25' stroke={{width:3,color:'#72905b'}} mask={{width:1,height:300}} animate={[{property:'maskWidth',from:1,to:W-2*M,duration:1.8,easing:'ease-in-out'}]}/>,
   T(mobile?'Your next\nstep.':'Your next step.',M,mobile?540:327,W-2*M,mobile?350:210,mobile?132:152,white,true,{motion:words}),
   T('Clearer.',M,mobile?923:541,W-2*M,230,mobile?156:168,lime,true,{motion:{...words,at:.8}}),
   T('Where do I begin?',M,mobile?1365:820,W-2*M,90,mobile?45:40,muted,false)
  ],0,3.48,'01 Your next step');
  scene([
   T('PRO TRADER',M,mobile?596:299,W-2*M,190,mobile?108:149,white,true,{align:'center',motion:words}),
   T('ACADEMY',M,mobile?803:495,W-2*M,205,mobile?142:152,lime,true,{align:'center',motion:{...words,at:.28}}),
   T('Learn with intention.',M,mobile?1160:785,W-2*M,103,mobile?46:48,muted,false,{align:'center'})
  ],3.48,2.84,'02 Academy reveal');
  scene([
   T('Learn.',M,mobile?260:299,mobile?W-2*M:790,165,mobile?120:138,white,true,{motion:words}),
   T('Explore.',M,mobile?429:478,mobile?W-2*M:790,175,mobile?120:138,lime,true,{motion:{...words,at:.65}}),
   T('Your chart-analysis workspace.',M,mobile?625:735,mobile?W-2*M:770,mobile?95:150,mobile?39:44,muted,false),
   ...ui('chart',mobile?92:994,mobile?878:248,mobile?896:800,mobile?624:558,'PROTrader · Illustrative demo')
  ],6.32,6.34,'03 Explore your workspace');
  scene([
   T('Practise',M,mobile?290:280,mobile?W-2*M:890,195,mobile?125:145,white,true,{motion:words}),
   T('with purpose.',M,mobile?485:477,mobile?W-2*M:890,170,mobile?97:98,lime,true,{motion:{...words,at:.4}}),
   T('Learn. Record. Ask.',M,mobile?746:740,mobile?W-2*M:809,115,mobile?44:52,muted,false),
   ...ui('notes',mobile?92:1005,mobile?1080:345,mobile?896:792,mobile?270:239,'Academy practice notes · Sample')
  ],12.66,5.34,'04 Practise with purpose');
  scene([
   T('ARIA',M,mobile?255:232,mobile?W-2*M:820,170,mobile?132:145,lime,true,{motion:words}),
   T('Understand\nthe reasoning.',M,mobile?440:430,mobile?W-2*M:850,310,mobile?92:92,white,true,{motion:{...words,at:.35}}),
   T('Including when to wait.',M,mobile?795:793,mobile?W-2*M:810,118,mobile?40:42,muted,false,{animate:enter(6)}),
   ...ui('aria',mobile?92:1038,mobile?1030:253,mobile?896:754,mobile?530:446,'PROTrader · Illustrative demo'),
   <group animate={enter(6)}><media file={assets.wait} x={mobile?92:1038} y={mobile?1610:784} width={mobile?896:754} height={mobile?128:108} fit='contain'/></group>
  ],18,12,'05 ARIA explains the checks');
  scene([
   T('ORACLE',M,mobile?238:211,mobile?W-2*M:830,135,mobile?94:101,lime,true,{motion:words}),
   T('The same checks.\nAnother view.',M,mobile?395:364,mobile?W-2*M:832,210,mobile?70:67,white,true,{motion:{...words,at:.35}}),
   T('8 / 9',M,mobile?674:582,mobile?W-2*M:806,215,mobile?160:151,white,true,{animate:enter(3.3)}),
   ...Array.from({length:9},(_,i)=><rect x={M+i*(mobile?102:86)} y={mobile?922:786} width={mobile?78:65} height={12} radius={6} fill={i<8?lime:'#394532'} animate={[{property:'opacity',from:0,to:1,at:3.3+i*.07,duration:.4}]}/>),
   T('About 89% confluence',M,mobile?974:840,mobile?W-2*M:832,80,mobile?42:40,lime,false,{animate:enter(4.3)}),
   ...ui('oracle',mobile?140:1050,mobile?1144:304,mobile?800:738,mobile?458:423,'Separate illustrative example'),
   T('Matching checks—not win probability.',mobile?M:1008,mobile?1740:850,mobile?W-2*M:810,80,mobile?35:33,white,false,{animate:enter(8.7)})
  ],30,15,'06 Confluence is a count');
  scene([
   T('Compare.',M,mobile?272:236,mobile?W-2*M:880,160,mobile?111:110,white,true,{motion:words}),
   T('Question.',M,mobile?443:412,mobile?W-2*M:880,160,mobile?111:110,white,true,{motion:{...words,at:.35}}),
   T('Decide.',M,mobile?614:588,mobile?W-2*M:880,160,mobile?111:110,lime,true,{motion:{...words,at:.7}}),
   T('You stay in control.',M,mobile?840:813,mobile?W-2*M:850,105,mobile?45:45,muted,false,{animate:enter(3)}),
   ...ui('chart',mobile?92:1010,mobile?1050:256,mobile?896:778,mobile?624:542,'Compare the output with the chart')
  ],45,9,'07 Your own reasoning');
  const academy=timing.scenes.find(s=>s.index===6), askAt=academy.starts[3];
  scene([
   T('Learn.\nThen practise.',M,mobile?267:260,mobile?W-2*M:850,360,mobile?112:108,white,true,{motion:words}),
   T('Keep a record\nof your thinking.',M,mobile?725:709,mobile?W-2*M:850,180,mobile?48:47,lime,false),
   ...ui('saved',mobile?92:1008,mobile?1090:311,mobile?896:780,mobile?522:455,'Academy · Sample learning account')
  ],54,askAt-54,'08 Save a practice reflection');
  scene([
   T('Ask your\ninstructor.',M,mobile?236:291,mobile?W-2*M:960,350,mobile?110:117,white,true,{motion:words}),
   T('Keep the conversation\nwith the lesson.',M,mobile?684:743,mobile?W-2*M:980,168,mobile?46:48,lime,false),
   ...ui('question',mobile?310:1260,mobile?954:177,mobile?460:466,mobile?730:740,null),
   T('Academy · Sample question',mobile?M:1080,mobile?1750:933,mobile?W-2*M:730,62,mobile?31:28,muted,false)
  ],askAt,67-askAt,'09 Ask a lesson question');
  scene([
   T('Start here.',M,mobile?290:247,W-2*M,210,mobile?143:156,lime,true,{motion:words}),
   T('One clear route into learning.',M,mobile?543:492,W-2*M,115,mobile?46:49,white,false),
   ...['Start here','The basics','Feature guides'].flatMap((label,i)=>{
    const x=mobile?M:M+i*579, y=mobile?836+i*245:680,w=mobile?W-2*M:548;
    return [<group animate={enter(i*1.6)}><rect x={x} y={y} width={w} height={180} radius={22} fill={i===0?'#c1f28b':'#182013'} strokeColor={i===0?'#c1f28b':'#566b43'} strokeWidth={2}/>{T(`0${i+1}`,x+28,y+26,74,62,33,i===0?ink:lime,false)}{T(label,x+28,y+90,w-56,66,mobile?51:43,i===0?ink:white,true)}</group>];
   })
  ],67,9,'10 Your beginner route');
  // The final state holds after the narration. No final fade to black.
  p.compose([
   T('PRO TRADER',M,mobile?336:222,W-2*M,185,mobile?108:126,white,true,{align:'center',motion:words}),
   T('ACADEMY',M,mobile?539:419,W-2*M,187,mobile?142:132,lime,true,{align:'center',motion:{...words,at:.25}}),
   T('Understand the tools.\nBuild your process.',M,mobile?869:649,W-2*M,195,mobile?60:51,white,false,{align:'center',animate:enter(1.5)}),
   <group animate={enter(4)}><rect x={mobile?171:615} y={mobile?1270:832} width={mobile?738:690} height={112} radius={56} fill={lime}/>{T('Begin the basics',mobile?195:640,mobile?1294:857,mobile?690:640,75,mobile?50:45,ink,true,{align:'center'})}</group>,
   T('protraderacademy.company',M,mobile?1530:950,W-2*M,50,mobile?36:24,muted,false,{align:'center',animate:enter(4.5)})
  ],{at:76,dur:11,name:'11 Begin the basics'});
  shots.push({at:76,dur:11,name:'11 Begin the basics'});
  await fs.mkdir(ROOT+'/frames-'+format,{recursive:true});
  for(const [i,s] of shots.entries()){
   await p.frame(s.at+Math.min(s.dur-.1,Math.max(1.1,s.dur*.68)),ROOT+`/frames-${format}/${String(i).padStart(2,'0')}.png`);
  }
  await p.frame(86,ROOT+`/frames-${format}/final.png`);
  await fs.writeFile(ROOT+'/shots.json',JSON.stringify(shots,null,2));
  if(!process.env.FRAMES_ONLY)await p.render(ROOT+`/silent-${format}.mp4`,{concurrency:2,bitrate:8000000,accel:'cpu'});
 }
};
