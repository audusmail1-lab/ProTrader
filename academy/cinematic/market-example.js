/* Deterministic Academy fixtures, not a market feed or generated signal. */
export const MARKET={symbol:'EUR/USD',currency:'USD',pip:.0001,contract:100000,lotStep:.01};
export const money=value=>new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(value);
export const price=value=>Number(value).toFixed(5);
export const bars=Array.from({length:76},(_,i)=>{
  const trend=1.0857+i*.000035;
  const base=trend+Math.sin(i*.31)*.00048+Math.sin(i*.93)*.00017;
  const open=base+Math.cos(i*1.83)*.00012,close=base+Math.sin(i*1.71)*.00015;
  return {open,close,high:Math.max(open,close)+.00008+Math.abs(Math.sin(i*2.17))*.00017,low:Math.min(open,close)-.00008-Math.abs(Math.cos(i*1.21))*.00017,volume:20+Math.round(Math.abs(Math.sin(i*.77))*62)};
});
const shift=1.0884-bars.at(-1).close;
bars.forEach(b=>{for(const k of ['open','close','high','low'])b[k]+=shift});
export function chartSVG({high=1.094,low=1.084,width=900,height=400,volume=true,visibleBars=bars.length}={}){
  const count=Math.max(1,Math.min(bars.length,Math.floor(visibleBars))),start=bars.length-count,visible=bars.slice(start);
  const x0=20,x1=width-78,y0=28,y1=height-36,step=(x1-x0)/(count+10);
  const y=p=>y0+(high-p)/(high-low)*(y1-y0);
  const grid=Array.from({length:6},(_,i)=>{const py=y0+i*(y1-y0)/5,p=high-i*(high-low)/5;return `<path d="M${x0} ${py}H${x1}"/><text x="${x1+10}" y="${py+4}">${price(p)}</text>`}).join('');
  const tickEvery=width<500?32:16;
  const tickIndices=visible.map((_,i)=>i).filter(i=>(start+i)%tickEvery===0);
  const times=tickIndices.map(i=>{const x=x0+step*(i+1),hour=(19+(start+i)/4)%24;return `<path d="M${x} ${y0}V${y1}"/><text x="${x}" y="${height-10}" text-anchor="${i===0?'start':'middle'}">${String(hour).padStart(2,'0')}:00</text>`}).join('');
  const candles=visible.map((b,i)=>{const x=x0+step*(i+1),up=b.close>=b.open;return `<g class="${up?'candle-up':'candle-down'}"><path d="M${x} ${y(b.high)}V${y(b.low)}"/><rect x="${x-step*.29}" y="${Math.min(y(b.open),y(b.close))}" width="${step*.58}" height="${Math.max(1.2,Math.abs(y(b.close)-y(b.open)))}"/>${volume?`<rect class="volume-bar" x="${x-step*.29}" y="${y1-b.volume*.38}" width="${step*.58}" height="${b.volume*.38}"/>`:''}</g>`}).join('');
  function average(period){const alpha=2/(period+1);let value=bars[0].close;return bars.map((b,i)=>{value=i?alpha*b.close+(1-alpha)*value:b.close;return value}).slice(start).map((value,i)=>`${i?'L':'M'}${x0+step*(i+1)} ${y(value)}`).join(' ')}
  return `<svg class="terminal-chart" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" aria-hidden="true"><g class="chart-grid">${grid}${times}</g><path class="ema-slow" d="${average(50)}"/><path class="ema-fast" d="${average(20)}"/>${candles}<path class="quote-line" d="M${x0} ${y(1.0884)}H${x1}"/><rect class="quote-badge" x="${x1}" y="${y(1.0884)-10}" width="76" height="20"/><text class="quote-text" x="${x1+8}" y="${y(1.0884)+4}">1.08840</text></svg>`;
}

export function calculatePlan({side='buy',balance,riskPercent,entry,stop,target,feePerLot=0,sizingMode='fixed',fixedLots=.48}){
  const errors={};
  if(!['fixed','auto'].includes(sizingMode))errors.sizingMode='Choose fixed size or automatic risk sizing.';
  if(sizingMode==='fixed'&&(!Number.isFinite(fixedLots)||fixedLots<.01||fixedLots>100||Math.abs(fixedLots/.01-Math.round(fixedLots/.01))>1e-7))errors.fixedLots='Use a position size from 0.01 to 100 lots in 0.01-lot steps.';
  if(!Number.isFinite(balance)||balance<100||balance>10000000)errors.balance='Use an account value from $100 to $10,000,000.';
  if(!Number.isFinite(riskPercent)||riskPercent<=0||riskPercent>5)errors.riskPercent='Use a risk percentage above 0 and no more than 5.';
  if(!Number.isFinite(feePerLot)||feePerLot<0||feePerLot>100)errors.feePerLot='Use a fee between $0 and $100 per lot.';
  for(const [k,v] of Object.entries({entry,stop,target}))if(!Number.isFinite(v)||v<.5||v>2)errors[k]='Use an EUR/USD example price between 0.50000 and 2.00000.';
  if(!['buy','sell'].includes(side))errors.side='Choose a long or short plan.';
  const sign=side==='buy'?1:-1,stopDistance=sign*(entry-stop),targetDistance=sign*(target-entry);
  if(!errors.entry&&!errors.stop&&stopDistance<MARKET.pip-1e-10)errors.stop=side==='buy'?'A long plan needs a stop at least 1 pip below entry.':'A short plan needs a stop at least 1 pip above entry.';
  if(!errors.entry&&!errors.target&&targetDistance<MARKET.pip-1e-10)errors.target=side==='buy'?'A long plan needs a target at least 1 pip above entry.':'A short plan needs a target at least 1 pip below entry.';
  if(Object.keys(errors).length)return {valid:false,errors};
  const budget=balance*riskPercent/100;
  const raw=budget/(stopDistance*MARKET.contract+feePerLot);
  const lots=sizingMode==='auto'?Math.floor((raw+1e-10)/MARKET.lotStep)*MARKET.lotStep:fixedLots;
  const costs=lots*feePerLot,grossRisk=lots*stopDistance*MARKET.contract,grossReward=lots*targetDistance*MARKET.contract;
  const risk=grossRisk+costs,reward=grossReward-costs;
  return {valid:true,errors,sizingMode,overBudget:risk-budget>.005,budget,lots,units:Math.round(lots*MARKET.contract),costs,grossRisk,grossReward,risk,reward,ratio:risk?reward/risk:0,grossRatio:targetDistance/stopDistance,stopPips:stopDistance/MARKET.pip,targetPips:targetDistance/MARKET.pip,notional:lots*MARKET.contract*entry,belowMinimum:lots<MARKET.lotStep};
}
