import fs from 'node:fs/promises';
const ROOT='/home/user/tutorial-final';
export default async ({project})=>{
 const all=JSON.parse(await fs.readFile(ROOT+'/timed-manifest.json','utf8'));
 const preview=process.env.PREVIEW_ONLY==='1';
 for(const v of all){
  const p=await project({dir:`${ROOT}/projects/${v.id}`,size:'1080x1920',fps:24,background:'#101611'});
  const regular=await p.add('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf');
  const bold=await p.add('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf');
  const T=(s,x,y,w,h,size=40,color='#f0f4ec',strong=false)=><text x={x} y={y} width={w} height={h} fontSize={size} lineHeight={1.17} color={color} typography={{fontAssetId:strong?bold.id:regular.id}}>{s}</text>;
  for(let i=0;i<v.shots.length;i++){
   const s=v.shots[i],a=s.asset;
   const title=v.title.replace('What Oracle’s percentage means','Understanding Oracle').replace('Find your flow with shortcuts','Desktop shortcuts');
   const nodes=[<rect width={1080} height={1920} fill='#101611'/>,<rect x={72} y={79} width={44} height={5} fill='#c0eb83'/>,T('PRO TRADER ACADEMY',140,60,865,48,30,'#c0eb83',true),T(title,72,149,936,153,54,'#f0f4ec',true),T(i===0?'THE IDEA':i===v.shots.length-1?'YOUR NEXT STEP':'GUIDED PRACTICE',72,319,760,48,29,'#b6c4ad'),T(String(i+1).padStart(2,'0')+' / '+v.shots.length,858,319,170,48,28,'#b6c4ad'),<rect x={54} y={408} width={972} height={902} radius={24} fill='#172019' strokeColor='#384733' strokeWidth={2}/>,<rect x={76} y={431} width={129} height={40} radius={9} fill='#2b391f'/>,T('PRACTICE',88,435,115,35,22,'#d5edb8',true),T('ILLUSTRATIVE EXAMPLE',234,435,741,42,25,'#b6c4ad'),<rect x={54} y={1400} width={972} height={354} radius={20} fill='#1c2919'/>,T(s.caption,87,1441,901,296,78,'#f3f7ec',true),T(s.subnote,72,1335,936,62,29,'#b6c4ad'),T('Educational only · Not financial advice',72,1803,936,51,27,'#a8b7a0'),<rect x={72} y={1872} width={936} height={4} fill='#36452f'/>,<rect x={72} y={1872} width={936*(i+1)/v.shots.length} height={4} fill='#c0eb83'/>];
   const opacity=(at=0)=>[{property:'opacity',keyframes:[{at:0,value:0},{at:Math.max(at,.001),value:0},{at:at+.32,value:1}]}];
   const addImage=async (asset,box,kind,delay=0)=>{
    const handle=await p.add(`${ROOT}/assets/${asset.prepared}`);
    const scale=Math.min(box[2]/asset.width,box[3]/asset.height);
    const w=asset.width*scale,h=asset.height*scale,x=box[0]+(box[2]-w)/2,y=box[1]+(box[3]-h)/2;
    nodes.push(<media file={handle} x={x} y={y} width={w} height={h} fit='contain' animate={opacity(delay)}/>);
    const hi=kind==='nav'?asset.highlight:kind==='asset'?s.highlight:null;
    if(hi)nodes.push(<rect x={x+hi[0]*scale} y={y+hi[1]*scale} width={hi[2]*scale} height={hi[3]*scale} radius={9} fill='#ffffff00' strokeColor='#c0eb83' strokeWidth={5} animate={opacity(.7)}/>);
    return{x,y,w,h,scale};
   };
   let box=[78,510,924,746];
   if(s.nav){await addImage(s.nav,[87,518,906,239],'nav');box=[87,784,906,458];}
   if(s.key){nodes.push(<rect x={393} y={504} width={294} height={74} radius={14} fill='#293822'/>,T(s.key,412,511,260,61,42,'#d5edb8',true));box=[87,611,906,631];}
   if(a.kind==='score8'||a.kind==='score6'){
    const score=a.kind==='score8'?8:6;
    nodes.push(T(a.title,102,543,873,61,38,'#bbccaf',true),T(score+' / 9',102,659,873,187,134,'#c0eb83',true),T('matching checks',102,855,873,85,51,'#e0e8d9'));
    for(let k=0;k<9;k++)nodes.push(<rect x={104+k*99} y={1004} width={77} height={77} radius={14} fill={k<score?'#c0eb83':'#4a5d41'}/>);
    nodes.push(T('≈ '+Math.round(score/9*100)+'% confluence',102,1137,873,107,67,'#f4f7ed',true));
   }else if(a.kind==='guide'){
    nodes.push(T(a.title,103,562,870,135,44,'#c0eb83',true));
    a.lines.forEach((line,k)=>nodes.push(<rect x={104} y={766+k*145} width={10} height={10} radius={5} fill='#c0eb83'/>,T(line,145,737+k*145,823,133,51,'#edf3e6',true)));
   }else{
    if(s.before)await addImage(s.before,box,'before');
    const g=await addImage(a,box,'asset',s.before?s.changeAt:0);
    if(s.point){
     const x=g.x+s.point[0]*g.scale,y=g.y+s.point[1]*g.scale;
     nodes.push(<group x={x} y={y} width={56} height={66} animate={[{property:'offsetX',from:92,to:0,at:.6,duration:.8,easing:'ease-in-out'},{property:'offsetY',from:86,to:0,at:.6,duration:.8,easing:'ease-in-out'},{property:'opacity',keyframes:[{at:0,value:0},{at:.6,value:0},{at:.9,value:1},{at:2.0,value:1},{at:2.5,value:0}]}]}><path d='M 0 0 L 0 42 L 12 32 L 22 53 L 32 48 L 22 28 L 42 27 Z' width={42} height={53} fill='#edf4e6' stroke={{color:'#162411',width:3}}/></group>);
    }
   }
   p.compose(nodes,{at:s.at,dur:s.dur,name:`${v.id}-${i} ${s.caption}`});
  }
  await fs.mkdir(`${ROOT}/frames`,{recursive:true});
  for(let i=0;i<v.shots.length;i++)await p.frame(v.shots[i].at+Math.min(3,v.shots[i].dur-.4),`${ROOT}/frames/${v.id}-${i}.png`);
  if(!preview){
   await p.render(`${ROOT}/silent-${v.id}.mp4`,{accel:'cpu',concurrency:2});
   console.log('RENDERED',v.id,v.duration);
  }
 }
};
