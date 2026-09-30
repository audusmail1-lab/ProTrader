import test from 'node:test';
import assert from 'node:assert/strict';
import {calculatePlan} from '../academy/cinematic/market-example.js';
const plan={sizingMode:'auto',side:'buy',balance:10000,riskPercent:1,entry:1.0884,stop:1.0864,target:1.0924,feePerLot:7};
const close=(a,b)=>assert.ok(Math.abs(a-b)<1e-7,`${a} differs from ${b}`);
test('USD EUR/USD plan sizes within a $100 budget including round-trip commission',()=>{const p=calculatePlan(plan);assert.equal(p.valid,true);close(p.lots,.48);close(p.risk,99.36);close(p.reward,188.64);close(p.costs,3.36);assert.equal(p.units,48000);assert.ok(p.risk<=p.budget)});
test('short-side prices produce the same size and signed outcome estimates',()=>{const p=calculatePlan({...plan,side:'sell',stop:1.0904,target:1.0844});close(p.lots,.48);close(p.risk,99.36);close(p.reward,188.64)});
test('wider stop reduces size while leaving the budget intact',()=>{const p=calculatePlan({...plan,stop:1.0844});close(p.lots,.24);close(p.risk,97.68);assert.ok(p.risk<=100)});
test('zero commission preserves exact $100 risk and 2R',()=>{const p=calculatePlan({...plan,feePerLot:0});close(p.lots,.5);close(p.risk,100);close(p.reward,200);close(p.ratio,2)});
test('one-pip boundary is accepted despite floating point representation',()=>{assert.equal(calculatePlan({...plan,stop:1.0883}).valid,true)});
test('incorrect-side stop, target, blank numbers, zero budget and excessive fee are rejected',()=>{for(const change of [{stop:1.09},{target:1.08},{entry:NaN},{balance:NaN},{riskPercent:0},{feePerLot:101},{side:'invalid'}])assert.equal(calculatePlan({...plan,...change}).valid,false)});
test('risk below the minimum volume is explicit, never rounded up',()=>{const p=calculatePlan({...plan,balance:100,riskPercent:.01});assert.equal(p.belowMinimum,true);assert.equal(p.lots,0)});
test('fees can make the target result negative and must not be shown as a gain',()=>{const p=calculatePlan({...plan,target:1.0885,feePerLot:100});assert.ok(p.reward<0);assert.ok(p.ratio<0)});

test('fixed size is the default and SL changes do not change TP profit or lots',()=>{
 const base={...plan,sizingMode:undefined,fixedLots:.48};
 for(const stop of [1.0854,1.0864,1.0874]){
  const p=calculatePlan({...base,stop});
  assert.equal(p.valid,true);close(p.lots,.48);close(p.reward,188.64);close(p.costs,3.36);
 }
 close(calculatePlan({...base,stop:1.0874}).risk,51.36);
 close(calculatePlan({...base,stop:1.0854}).risk,147.36);
 assert.equal(calculatePlan({...base,stop:1.0854}).overBudget,true);
});
test('short fixed-size plans also preserve target profit while SL changes risk',()=>{
 const base={...plan,sizingMode:'fixed',fixedLots:.48,side:'sell',target:1.0844};
 for(const stop of [1.0894,1.0904,1.0914])close(calculatePlan({...base,stop}).reward,188.64);
 close(calculatePlan({...base,stop:1.0894}).risk,51.36);
 close(calculatePlan({...base,stop:1.0914}).risk,147.36);
});
test('risk reference changes never silently resize a fixed plan',()=>{
 const p=calculatePlan({...plan,sizingMode:'fixed',fixedLots:.48,balance:1000,riskPercent:.5});
 close(p.lots,.48);close(p.reward,188.64);assert.equal(p.overBudget,true);
});
test('invalid fixed sizes and sizing modes are rejected without rounding exposure up',()=>{
 for(const fixedLots of [NaN,0,-1,.005,.015,100.01])assert.equal(calculatePlan({...plan,sizingMode:'fixed',fixedLots}).valid,false);
 assert.equal(calculatePlan({...plan,sizingMode:'unrecognised'}).valid,false);
});
