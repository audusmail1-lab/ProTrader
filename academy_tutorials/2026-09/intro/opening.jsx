// Revised opening audition: native motion, word-led captions and real product crops.
import fs from 'node:fs/promises';
const ROOT='/home/user/academy-callan';
export default async ({project})=>{
 const timing=JSON.parse(await fs.readFile(ROOT+'/timing.json','utf8'));
 const {duration:D,welcome:a,learn:b,then:c}=timing;
 const p=await project({dir:ROOT+'/project',size:'1920x1080',fps:30,background:'#070b08'});
 const bold=await p.add('/usr/share/fonts/truetype/higgsfield/Metropolis-ExtraBold.ttf');
 const regular=await p.add('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf');
 const chart=await p.add(ROOT+'/input/assets/1-5-asset.jpg');
 const notes=await p.add(ROOT+'/input/assets/3-8-asset.jpg');
 const ink='#070b08',lime='#c1f28b',white='#f2f4ec',muted='#aab8a5';
 const fade=d=>[{property:'opacity',keyframes:[{at:0,value:0},{at:.28,value:1},{at:d-.26,value:1},{at:d-.02,value:0}]}];
 const words={by:'word',from:{y:24,opacity:0},at:.1,duration:.55,overlap:.8,easing:'house'};
 const T=(s,x,y,w,h,size=100,color=white,strong=true,extra={})=><text x={x} y={y} width={w} height={h} fontSize={size} color={color} lineHeight={1.12} typography={{fontAssetId:strong?bold.id:regular.id}} {...extra}>{s}</text>;
 const scene=(nodes,at,dur,name)=>p.compose(nodes,{at,dur,name});
 scene([
  <rect width={1920} height={1080} fill={ink}/>,
  <rect x={340} y={-600} width={2140} height={2050} fill={{kind:'radial',stops:[{offset:0,color:'#29451c',opacity:.75},{offset:.75,color:ink,opacity:0}]}}/>,
  <rect x={104} y={60} width={30} height={4} fill={lime}/>,T('PRO TRADER ACADEMY',154,45,1080,52,26,muted,false,{letterSpacing:2}),
  T('OPENING PREVIEW',1410,45,405,52,23,muted,false,{align:'right'}),
  <rect x={104} y={986} width={1712} height={1} fill='#34412d'/>,
  T('Educational only · Not financial advice',104,1006,1680,51,26,muted,false)
 ],0,D,'Brand atmosphere');
 scene([
  <path x={104} y={270} width={1712} height={300} d='M 0 245 C 210 245 270 190 405 190 C 620 190 674 65 860 65 C 1110 65 1180 145 1340 145 C 1530 145 1600 25 1712 25' stroke={{width:3,color:'#72905b'}} mask={{width:1,height:300}} animate={[{property:'maskWidth',from:1,to:1712,duration:1.8,easing:'ease-in-out'},...fade(a)]}/>,
  T('Your next step.',104,327,1712,210,152,white,true,{motion:words}),
  T('Clearer.',104,541,1712,220,168,lime,true,{motion:{...words,at:.8}}),
  T('Where do I begin?',110,820,1650,87,40,muted,false,{animate:fade(a)})
 ],0,a,'01 An inviting question');
 // Native text moves as one headline group; no artificial interface is invented.
 scene([
  <group animate={fade(b-a)}>
   {T('PRO TRADER',104,299,1712,191,149,white,true,{align:'center',motion:words})}
   {T('ACADEMY',104,495,1712,204,152,lime,true,{align:'center',motion:{...words,at:.28}})}
   {T('Learn with intention.',104,785,1712,103,48,muted,false,{align:'center'})}
  </group>
 ],a,b-a,'02 Academy reveal');
 scene([
  <group animate={fade(c-b)}>
   {T('Learn.',104,299,790,165,138,white,true,{motion:words})}
   {T('Explore.',104,478,790,171,138,lime,true,{motion:{...words,at:.65}})}
   {T('Your chart-analysis\nworkspace.',110,720,780,160,46,muted,false)}
   <rect x={928} y={259} width={893} height={573} radius={26} fill='#172314' strokeColor='#617450' strokeWidth={2}/>
   <media file={chart} x={950} y={281} width={849} height={509} fit='contain' animate={[{property:'scale',from:1.025,to:1,at:0,duration:Math.max(1,c-b-.2),easing:'ease-in-out'}]}/>
   {T('PROTrader · Illustrative demo',963,854,832,67,30,muted,false)}
  </group>
 ],b,c-b,'03 A genuine chart observation');
 scene([
  <group animate={fade(D-c)}>
   {T('Practise',104,280,890,195,145,white,true,{motion:words})}
   {T('with purpose.',104,477,890,173,98,lime,true,{motion:{...words,at:.4}})}
   {T('Learn. Record. Ask.',110,740,809,120,52,muted,false)}
   <rect x={1040} y={228} width={773} height={466} radius={26} fill='#172314' strokeColor='#617450' strokeWidth={2}/>
   <media file={notes} x={1064} y={252} width={725} height={394} fit='contain'/>
   {T('Academy practice notes · Sample',1058,727,747,92,29,muted,false)}
  </group>
 ],c,D-c,'04 Connect analysis to guided practice');
 await fs.mkdir(ROOT+'/frames',{recursive:true});
 for(const [i,t] of [Math.min(2,a-.2),(a+b)/2,(b+c)/2,(c+D)/2].entries())await p.frame(t,ROOT+`/frames/scene-${i}.png`);
 await p.render(ROOT+'/silent.mp4',{concurrency:2,bitrate:8000000,accel:'cpu'});
};
