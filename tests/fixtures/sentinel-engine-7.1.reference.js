// Frozen independent JavaScript reference. Test-only; never loaded by the app.
// Source commit 16ff806c11069b9c937fedd1a5ebdf6f2df15bad; see adjacent provenance JSON.
function calcEMA(arr, p) {
  const k = 2 / (p + 1); let e = arr[0];
  return arr.map(v => { e = v * k + e * (1 - k); return e; });
}
function calcSMA(arr, p) {
  return arr.map((_, i) => {
    if (i < p - 1) return null;
    return arr.slice(i - p + 1, i + 1).reduce((a, b) => a + b, 0) / p;
  });
}
function calcRSI(closes, p = 14) {
  const chg = closes.slice(1).map((c, i) => c - closes[i]);
  const out = new Array(p).fill(null);
  let ag = chg.slice(0, p).filter(x => x > 0).reduce((a, b) => a + b, 0) / p;
  let al = chg.slice(0, p).filter(x => x < 0).map(Math.abs).reduce((a, b) => a + b, 0) / p;
  out.push(al === 0 ? 100 : 100 - 100 / (1 + ag / al));
  for (let i = p; i < chg.length; i++) {
    const g = chg[i] > 0 ? chg[i] : 0, l = chg[i] < 0 ? Math.abs(chg[i]) : 0;
    ag = (ag * (p - 1) + g) / p; al = (al * (p - 1) + l) / p;
    out.push(al === 0 ? 100 : 100 - 100 / (1 + ag / al));
  }
  return out;
}
function calcMACD(closes) {
  const e12 = calcEMA(closes, 12), e26 = calcEMA(closes, 26);
  const line = e12.map((v, i) => v - e26[i]), sig = calcEMA(line, 9);
  return { line, sig, hist: line.map((v, i) => v - sig[i]) };
}
function calcBB(closes, p = 20, m = 2) {
  return closes.map((_, i) => {
    if (i < p - 1) return null;
    const sl = closes.slice(i - p + 1, i + 1), mn = sl.reduce((a, b) => a + b, 0) / p;
    const std = Math.sqrt(sl.reduce((a, b) => a + (b - mn) ** 2, 0) / p);
    return { upper: mn + m * std, middle: mn, lower: mn - m * std };
  });
}
function calcStoch(cdles, k = 14, d = 3) {
  const kArr = cdles.map((_, i) => {
    if (i < k - 1) return null;
    const sl = cdles.slice(i - k + 1, i + 1), hi = Math.max(...sl.map(c => c.high)), lo = Math.min(...sl.map(c => c.low));
    return hi === lo ? 50 : ((cdles[i].close - lo) / (hi - lo)) * 100;
  });
  const dArr = kArr.map((_, i) => {
    const sl = kArr.slice(Math.max(0, i - d + 1), i + 1).filter(v => v !== null);
    return sl.length === d ? sl.reduce((a, b) => a + b, 0) / d : null;
  });
  return { k: kArr, d: dArr };
}
function calcATR(cdles, p = 14) {
  const trs = cdles.map((c, i) => {
    if (i === 0) return c.high - c.low;
    const prev = cdles[i-1].close;
    return Math.max(c.high - c.low, Math.abs(c.high - prev), Math.abs(c.low - prev));
  });
  return calcSMA(trs, p);
}


const ARIA_LAWS = [
  { n:1, name:'Mirror Law', body:'Price returns to the last significant structural mirror. Every key level creates a magnetic zone. Trade the reaction at the mirror.' },
  { n:2, name:'Dead Cat Bounce', body:'Corrective bounces die at 38.2% or 50% Fibonacci retracement. Wait for rejection confirmation before entering.' },
  { n:3, name:'Deceleration Law', body:'Three consecutive shrinking candle bodies at a key level = imminent reversal. The third shrink with rejection wick is the signal.' },
  { n:4, name:'Wyckoff Spring', body:'Wyckoff Spring is ONLY valid when followed by a Sign of Strength candle closing back above the level within 3 bars.' },
  { n:5, name:'Velocity Law', body:'Slow grinding break = likely fake. Fast decisive break with body ≥ 1.5×ATR = real momentum.' },
  { n:6, name:'Fair Value Gap', body:'Fair Value Gaps (3-candle imbalances) fill 80% of the time. Use the FVG midpoint as a high-probability entry zone.' },
  { n:7, name:'Confirmation Law', body:'ALWAYS wait for candle close confirmation. NEVER enter on a breakout candle while it is still forming.' },
  { n:8, name:'Session Law', body:'Dead zone (02:00–06:00 UTC) = 70% false moves. Peak quality: London open (07:00–10:00) and NY open (13:00–16:00).' },
  { n:9, name:'Momentum Law', body:'A move must sustain for at least 3 consecutive candles in the same direction to be real momentum.' },
  { n:10, name:'Fibonacci Law', body:'Highest-probability zones: 50% and 61.8% retracement. Only trade Fib levels with ≥2 additional confluence factors.' },
  { n:11, name:'Iron Stop Law', body:'The stop loss is IRON — never move it against the trade. Set it before entry. Lock it. Never touch it.' },
  { n:12, name:'MSS Law', body:'Market Structure Shift confirmed ONLY by candle CLOSE above swing high (bullish) or below swing low (bearish).' },
  { n:13, name:'ATR Stop Law', body:'Minimum stop loss distance = 1.5×ATR(14). If structure-based SL is tighter, use 1.5×ATR as your floor.' },
  { n:14, name:'MCC Supremacy', body:'Market Condition Classification overrides ALL other signals. If MCC says no — no means no.' },
];

let AM = { totalSig: 0, wins: 0, lastVerdict: null };

// ARIA v7.1 gate settings. sentinel_engine.py mirrors these exactly
// (tests/sentinel-parity.test.cjs fails if they drift).
const ARIA_GATE_COUNT = 10;
const ARIA_EXEC_MIN = 9, ARIA_QUAL_MIN = 8, ARIA_WAIT_MIN = 6;
const ARIA_ATR_BAND = [0.6, 1.8];
const ARIA_PATTERN_RECENT = 3;
const ARIA_FIB_ZONE = [0.45, 0.668], ARIA_FIB_RECENT = 5, ARIA_FIB_MIN_LEG_ATR = 3;

function ariaMCC(cdles, closes, ema20v, ema50v, atrV) {
  const n = closes.length, last = closes[n-1], e20 = ema20v[n-1], e50 = ema50v[n-1];
  const atr = atrV[n-1] || last * 0.002;
  const hr = new Date().getUTCHours();
  if (hr >= 2 && hr < 6) return { code:'DEAD_ZONE', label:'Dead Zone', cls:'mcc-dz', desc:'02:00–06:00 UTC. 70% fake moves. OBSERVER mode.' };
  const isUp = last > e20 && last > e50 && e20 > e50;
  const isDn = last < e20 && last < e50 && e20 < e50;
  const rAtr = atrV.slice(-20).filter(Boolean);
  const avgAtr = rAtr.length ? rAtr.reduce((a, b) => a + b, 0) / rAtr.length : atr;
  const isVol = atr > avgAtr * 2;
  const prevHi = Math.max(...closes.slice(-15, -1)), prevLo = Math.min(...closes.slice(-15, -1));
  const lc = cdles[n-1];
  const isFk = (lc.high > prevHi && lc.close < prevHi) || (lc.low < prevLo && lc.close > prevLo);
  const hi20 = Math.max(...closes.slice(-20)), lo20 = Math.min(...closes.slice(-20));
  const range = hi20 - lo20;
  const isRng = range < atr * 3.5 && !isUp && !isDn;
  if (isFk) return { code:'FAKE_BREAK', label:'Fake Break', cls:'mcc-fk', desc:'False break detected. Reduce size 50%. Expect mean reversion.' };
  if (isVol) return { code:'VOLATILE', label:'Volatile', cls:'mcc-vol', desc:'ATR spike >2× avg. Widen stops significantly.' };
  if (isUp) return { code:'TREND_UP', label:'Trend ↑', cls:'mcc-up', desc:'Clean uptrend: Price > EMA20 > EMA50. Long bias active.' };
  if (isDn) return { code:'TREND_DOWN', label:'Trend ↓', cls:'mcc-dn', desc:'Clean downtrend: Price < EMA20 < EMA50. Short bias active.' };
  if (isRng) return { code:'RANGING', label:'Ranging', cls:'mcc-rng', desc:'Price in <3.5×ATR band. Range-trade only.' };
  return { code:'TRANSITION', label:'Transition', cls:'mcc-tr', desc:'Mixed signals. Wait for structure clarity.' };
}

function ariaWyckoff(cdles, closes, ema20v, ema50v) {
  const n = closes.length, last = closes[n-1], e20 = ema20v[n-1], e50 = ema50v[n-1];
  const hi50 = Math.max(...closes.slice(-Math.min(50, n)));
  const lo50 = Math.min(...closes.slice(-Math.min(50, n)));
  const pos = (last - lo50) / ((hi50 - lo50) || 1);
  const bod = cdles.slice(-10).map(c => Math.abs(c.close - c.open));
  const avgB = bod.reduce((a, b) => a + b, 0) / bod.length || 1;
  const lstB = Math.abs(cdles[n-1].close - cdles[n-1].open);
  const lc = cdles[n-1];
  if (lc.low < lo50 && lc.close > lo50 * 0.9995) return { phase:'SPRING', desc:'Wyckoff Spring! Watch for SOS candle within 3 bars (Law 4).' };
  if (pos > 0.8 && e20 > e50 && last > e20) {
    if (lstB < avgB * 0.6) return { phase:'DISTRIBUTION', desc:'Shrinking bodies at highs = smart money distributing.' };
    return { phase:'MARKUP', desc:'Markup phase. EMAs aligned bullish. Trend continuation bias.' };
  }
  if (pos < 0.2 && e20 < e50 && last < e20) {
    if (lstB < avgB * 0.6) return { phase:'ACCUMULATION', desc:'Shrinking bodies at lows = smart money absorbing supply.' };
    return { phase:'MARKDOWN', desc:'Markdown phase. EMAs aligned bearish.' };
  }
  if (pos > 0.35 && pos < 0.65) return { phase:'CAUSE', desc:'Mid-range consolidation. Building cause for next directional move.' };
  return { phase:'TRANSITION', desc:'No high-probability Wyckoff setup currently active.' };
}

function ariaGates(cdles, closes, ema20v, ema50v, ema200v, rsiV, macdV, stochV, atrV, patternAligned) {
  const n = closes.length, last = closes[n-1], e20 = ema20v[n-1], e50 = ema50v[n-1];
  const rsi = rsiV[n-1], atr = atrV[n-1] || 1;
  const dir = (last > e20 && e20 > e50) ? 'buy' : 'sell';
  const G = [];

  const g1 = dir === 'buy' ? (last > e20 && e20 > e50) : (last < e20 && e20 < e50);
  G.push({ name:'EMA Stack', pass:g1, detail:g1 ? `✓ ${dir==='buy'?'Bullish':'Bearish'} aligned` : '✗ EMAs not aligned' });

  const g2 = dir === 'buy' ? (rsi > 50 && rsi < 75) : (rsi < 50 && rsi > 25);
  G.push({ name:'RSI Momentum', pass:g2, detail:`RSI ${rsi?.toFixed(1)} — ${g2?'✓ confirms':'✗ weak'}` });

  let g3 = false;
  if (macdV?.line?.length >= n) { const ml = macdV.line[n-1], ms = macdV.sig[n-1]; g3 = dir === 'buy' ? ml > ms : ml < ms; }
  G.push({ name:'MACD Direction', pass:g3, detail:g3 ? '✓ MACD confirms' : '✗ MACD opposing' });

  const sl2 = cdles.slice(-10); let hhll = 0;
  for (let i = 2; i < sl2.length; i++) {
    if (dir==='buy' && sl2[i].high > sl2[i-2].high && sl2[i].low > sl2[i-2].low) hhll++;
    if (dir==='sell' && sl2[i].low < sl2[i-2].low && sl2[i].high < sl2[i-2].high) hhll++;
  }
  const g4 = hhll >= 2;
  G.push({ name:'Market Structure', pass:g4, detail:g4 ? `✓ ${dir==='buy'?'HH+HL':'LL+LH'}` : '✗ Structure unclear' });

  const lc = cdles[n-1], pc = cdles[n-2];
  const eng = dir==='buy' ? (lc.close>lc.open && lc.close>pc.high) : (lc.close<lc.open && lc.close<pc.low);
  const pin = dir==='buy' ? (lc.low<pc.low && lc.close>(lc.high+lc.low)/2) : (lc.high>pc.high && lc.close<(lc.high+lc.low)/2);
  const bdy = dir==='buy' ? lc.close>lc.open : lc.close<lc.open;
  const g5 = eng || pin || bdy;
  G.push({ name:'Live Candle', pass:g5, detail:g5 ? `✓ ${eng?'Engulf':pin?'Pin bar':'Body confirms'}` : '✗ Current candle opposes' });

  // ATR Band (v7.1): volatility must be normal for this market — not dead
  // (spread dominates, stops sit in noise) and not blown out (stops too wide).
  const atrHist = atrV.slice(-100).filter(Boolean);
  const atrMean = atrHist.length ? atrHist.reduce((a, b) => a + b, 0) / atrHist.length : 0;
  const atrRatio = atrMean > 0 && atrV[n-1] ? atrV[n-1] / atrMean : 0;
  const g6 = atrRatio >= ARIA_ATR_BAND[0] && atrRatio <= ARIA_ATR_BAND[1];
  G.push({ name:'ATR Band', pass:g6, detail:`ATR ${atrRatio.toFixed(2)}× its 100-bar average — ${g6?'✓ normal':atrRatio < ARIA_ATR_BAND[0]?'✗ too quiet':'✗ too wild'}` });

  const e200 = ema200v?.[n-1];
  let g7;
  if (e200) { g7 = dir==='buy' ? last > e200 : last < e200; }
  else { const hiN = Math.max(...closes.slice(-Math.min(100,n))), loN = Math.min(...closes.slice(-Math.min(100,n))); g7 = dir==='buy' ? last>(hiN+loN)/2 : last<(hiN+loN)/2; }
  G.push({ name:'Macro Align', pass:g7, detail:g7 ? `✓ ${e200?'EMA200':'100-bar'} aligned` : '✗ Against macro' });

  let g8 = false;
  if (stochV?.k?.length >= n) { const kv = stochV.k[n-1]; g8 = kv !== null && (dir==='buy' ? kv<50 : kv>50); }
  G.push({ name:'Stochastic', pass:g8, detail:g8 ? '✓ Stoch confirms' : '✗ Stoch opposing' });

  const g9 = !!patternAligned;
  G.push({ name:'Pattern Gate', pass:g9, detail:g9 ? `✓ ${patternAligned} (last ${ARIA_PATTERN_RECENT} bars)` : `✗ No pattern in the last ${ARIA_PATTERN_RECENT} bars` });

  const fib = ariaFib(cdles, atrV, dir);
  G.push({ name:'Fibonacci Zone', pass:fib.pass, detail:fib.detail });

  const score = G.reduce((a, g) => a + (g.pass ? 1 : 0), 0);
  return { gates: G, score, dir };
}

function ariaEntry(cdles, closes, atrV, dir, mcc) {
  const n = closes.length, last = closes[n-1], atr = atrV[n-1] || last * 0.002;
  const slM = mcc?.code==='VOLATILE' ? 2.5 : mcc?.code==='FAKE_BREAK' ? 2.0 : 1.5;
  const sl = atr * slM, sign = dir==='buy' ? 1 : -1;
  const entry = last, slLevel = entry - sign * sl;
  const tp1 = entry + sign * sl * 1.5, tp2 = entry + sign * sl * 2.5, tp3 = entry + sign * sl * 4.0;
  const riskDollars = S.balance * S.riskPct / 100;
  const stopPct = entry ? Math.abs(sl / entry) * 100 : 0;
  const notional = stopPct > 0 ? riskDollars / (stopPct / 100) : 0;
  const riskText = Number.isFinite(notional) && notional > 0
    ? `$${riskDollars.toFixed(0)} risk · ~$${Math.min(notional, S.balance * 5).toLocaleString(undefined,{maximumFractionDigits:0})} max notional`
    : `$${riskDollars.toFixed(0)} risk`;
  return { entry, slLevel, tp1, tp2, tp3, sl, lotSize: riskText, dp: S.dp };
}

function ariaVerdict(score, mcc, sym, dir) {
  if (mcc.code==='DEAD_ZONE' || mcc.code==='FAKE_BREAK') return { v:'OBSERVER', cls:'verdict-obs', msg:`👁 OBSERVER — ${mcc.code==='DEAD_ZONE'?'Dead zone':'Fake break detected'}` };
  // NAS100 protocol: news-week shorts blocked + 80%+ confluence required (Joel's rule)
  const isNAS = sym === 'frxNAS100';
  if (isNAS && S.newsWeek && dir === 'sell') {
    return { v:'BLOCKED', cls:'verdict-obs', msg:`🛑 BLOCKED — NAS100 short during news week (Joel's rule)` };
  }
  const execThreshold = ARIA_EXEC_MIN;   // execution-ready requires stronger confluence than setup qualification
  const watchThreshold = ARIA_QUAL_MIN;
  if (score >= execThreshold) return { v:'EXEC_READY', cls:'verdict-armed', msg:`🎯 EXECUTION READY — ${score}/${ARIA_GATE_COUNT} gates${isNAS?' · NAS protocol':''}` };
  if (score >= watchThreshold) return { v:'QUALIFIED', cls:'verdict-wait', msg:`⚡ QUALIFIED SETUP — ${score}/${ARIA_GATE_COUNT} gates · wait for execution trigger` };
  if (score >= ARIA_WAIT_MIN) return { v:'WAITING', cls:'verdict-wait', msg:`⏳ WAITING — ${score}/${ARIA_GATE_COUNT} (need ≥${watchThreshold})` };
  return { v:'OBSERVER', cls:'verdict-obs', msg:`👁 OBSERVER — ${score}/${ARIA_GATE_COUNT} (insufficient confluence)` };
}

// Pattern Gate (v7.1): only a pattern completed on one of the last
// ARIA_PATTERN_RECENT candles counts. The old 30-bar lookback passed on every
// setup (one-year replay: 100%), so it filtered nothing.
function getPatternAlignment(dir, cdles = S.candles) {
  const n = cdles.length, want = dir === 'buy' ? 'bull' : 'bear';
  if (n < 20) return null;
  let best = null;
  PATTERNS.forEach(p => {
    if (p.dir !== want) return;
    for (let i = Math.max(15, n - ARIA_PATTERN_RECENT); i < n; i++) {
      let r = null;
      try { r = p.detect(cdles, i); } catch (_) { r = null; }
      if (r && r.conf >= 75 && (!best || r.conf > best.conf)) best = { name: p.name, conf: r.conf };
    }
  });
  return best ? best.name : null;
}

// Fibonacci Zone (v7.1, Law 10). Objective and mechanical:
//  • impulse leg = the extreme of the last 60 bars and the opposite extreme
//    in the 60 bars before it; it must be at least 3× ATR long
//  • the pullback since that extreme must reach the 50–61.8% zone
//    (tolerance: 45%–66.8%), and that touch must be within the last 5 bars
//  • price must have turned from the touch and not broken back past the extreme
function ariaFib(cdles, atrV, dir) {
  const n = cdles.length, W = 60, atr = atrV[n-1] || 0;
  const fail = d => ({ pass:false, detail:'✗ ' + d, r:null });
  if (n < 30 || !(atr > 0)) return fail('not enough data');
  const start = Math.max(0, n - W), last = cdles[n-1].close;
  const hi = i => cdles[i].high, lo = i => cdles[i].low;
  let ext = start;
  for (let i = start; i < n; i++) if (dir === 'buy' ? hi(i) > hi(ext) : lo(i) < lo(ext)) ext = i;
  if (ext > n - 2) return fail('no pullback yet');
  let orig = -1;
  for (let i = Math.max(0, ext - W); i < ext; i++) if (orig < 0 || (dir === 'buy' ? lo(i) < lo(orig) : hi(i) > hi(orig))) orig = i;
  if (orig < 0) return fail('no swing found');
  let pb = ext + 1;
  for (let i = ext + 1; i < n; i++) if (dir === 'buy' ? lo(i) <= lo(pb) : hi(i) >= hi(pb)) pb = i;
  const H = dir === 'buy' ? hi(ext) : hi(orig), L = dir === 'buy' ? lo(orig) : lo(ext);
  const leg = H - L;
  if (!(leg >= ARIA_FIB_MIN_LEG_ATR * atr)) return fail('last swing too small');
  const r = dir === 'buy' ? (H - lo(pb)) / leg : (hi(pb) - L) / leg;
  const pct = (r * 100).toFixed(0) + '%';
  if (r < ARIA_FIB_ZONE[0]) return fail(`pullback only ${pct} (needs 50–61.8%)`);
  if (r > 1) return fail(`swing fully retraced (${pct}) — no pullback to trade`);
  if (r > ARIA_FIB_ZONE[1]) return fail(`pullback ${pct} — past 61.8%`);
  if (n - 1 - pb > ARIA_FIB_RECENT) return fail(`zone touch ${n - 1 - pb} bars ago`);
  const turned = dir === 'buy' ? (last > lo(pb) && last < H) : (last < hi(pb) && last > L);
  if (!turned) return fail('no reaction from the zone yet');
  return { pass:true, detail:`✓ ${pct} retrace of the last swing`, r };
}


const PATTERNS = [
  { name:'Bullish Engulfing', dir:'bull', detect:(c,i)=>{
    if (i<1) return null;
    const cur=c[i], pr=c[i-1];
    if (!(cur.close>cur.open && pr.close<pr.open && cur.close>pr.open && cur.open<pr.close)) return null;
    const curBody=cur.close-cur.open, prBody=pr.open-pr.close;
    const ratio = prBody>0 ? curBody/prBody : 1;
    const conf = Math.min(95, 55 + Math.round(ratio*20));
    return { start:i-1, i, key:cur.close, key2:pr.close, kind:'rect', conf };
  }},
  { name:'Bearish Engulfing', dir:'bear', detect:(c,i)=>{
    if (i<1) return null;
    const cur=c[i], pr=c[i-1];
    if (!(cur.close<cur.open && pr.close>pr.open && cur.close<pr.open && cur.open>pr.close)) return null;
    const curBody=cur.open-cur.close, prBody=pr.close-pr.open;
    const ratio = prBody>0 ? curBody/prBody : 1;
    const conf = Math.min(95, 55 + Math.round(ratio*20));
    return { start:i-1, i, key:cur.close, key2:pr.close, kind:'rect', conf };
  }},
  { name:'Hammer', dir:'bull', detect:(c,i)=>{
    const x=c[i], body=Math.abs(x.close-x.open), lo=Math.min(x.close,x.open)-x.low, hi=x.high-Math.max(x.close,x.open);
    if (!(body>0 && lo>body*2 && hi<body*0.5)) return null;
    const ratio = body>0 ? lo/body : 0;
    const conf = Math.min(92, 55 + Math.round((ratio-2)*8));
    return { start:i, i, key:x.low, kind:'level', conf };
  }},
  { name:'Shooting Star', dir:'bear', detect:(c,i)=>{
    const x=c[i], body=Math.abs(x.close-x.open), hi=x.high-Math.max(x.close,x.open), lo=Math.min(x.close,x.open)-x.low;
    if (!(body>0 && hi>body*2 && lo<body*0.5)) return null;
    const ratio = body>0 ? hi/body : 0;
    const conf = Math.min(92, 55 + Math.round((ratio-2)*8));
    return { start:i, i, key:x.high, kind:'level', conf };
  }},
  { name:'Doji', dir:'neut', detect:(c,i)=>{
    const x=c[i], body=Math.abs(x.close-x.open), range=x.high-x.low;
    if (!(range>0 && body/range < 0.1)) return null;
    const conf = Math.round(60 + (1 - body/(range||1))*30);
    return { start:i, i, key:x.close, kind:'level', conf };
  }},
  { name:'Double Top', dir:'bear', detect:(c,i)=>{
    if (i<10) return null;
    const slice=c.slice(i-10,i+1), highs=slice.map(x=>x.high);
    const m=Math.max(...highs);
    const peaks=[]; highs.forEach((h,k)=>{ if (h>m*0.999) peaks.push(k); });
    if (peaks.length<2) return null;
    if (peaks[peaks.length-1]-peaks[0]<3) return null; // need separation
    const conf = Math.min(88, 65 + peaks.length*4);
    return { start:i-10+peaks[0], i:i-10+peaks[peaks.length-1], key:m, kind:'lineH', conf };
  }},
  { name:'Double Bottom', dir:'bull', detect:(c,i)=>{
    if (i<10) return null;
    const slice=c.slice(i-10,i+1), lows=slice.map(x=>x.low);
    const m=Math.min(...lows);
    const troughs=[]; lows.forEach((l,k)=>{ if (l<m*1.001) troughs.push(k); });
    if (troughs.length<2) return null;
    if (troughs[troughs.length-1]-troughs[0]<3) return null;
    const conf = Math.min(88, 65 + troughs.length*4);
    return { start:i-10+troughs[0], i:i-10+troughs[troughs.length-1], key:m, kind:'lineH', conf };
  }},
  { name:'Head & Shoulders', dir:'bear', detect:(c,i)=>{
    if (i<15) return null;
    const slice=c.slice(i-15,i+1), highs=slice.map(x=>x.high);
    const m=Math.max(...highs), mi=highs.indexOf(m);
    if (!(mi>3 && mi<highs.length-3 && highs[mi-3]<m*0.97 && highs[mi+3]<m*0.97)) return null;
    const symmetry = Math.abs(highs[mi-3]-highs[mi+3]) / m;
    const conf = Math.min(86, 62 + Math.round((0.05-symmetry)*400));
    return { start:i-15, i, key:m, kind:'rect', conf };
  }},
  { name:'Asc Triangle', dir:'bull', detect:(c,i)=>{
    if (i<8) return null;
    const slice=c.slice(i-8,i+1), highs=slice.map(x=>x.high), lows=slice.map(x=>x.low);
    const hRange = Math.max(...highs)-Math.min(...highs);
    if (!(hRange<highs[0]*0.01 && lows[lows.length-1]>lows[0])) return null;
    const tightness = 1 - (hRange/(highs[0]*0.01));
    const conf = Math.min(80, 60 + Math.round(tightness*20));
    return { start:i-8, i, key:Math.max(...highs), key2:lows[0], kind:'wedge', conf };
  }},
  { name:'Desc Triangle', dir:'bear', detect:(c,i)=>{
    if (i<8) return null;
    const slice=c.slice(i-8,i+1), highs=slice.map(x=>x.high), lows=slice.map(x=>x.low);
    const lRange = Math.max(...lows)-Math.min(...lows);
    if (!(lRange<lows[0]*0.01 && highs[highs.length-1]<highs[0])) return null;
    const tightness = 1 - (lRange/(lows[0]*0.01));
    const conf = Math.min(80, 60 + Math.round(tightness*20));
    return { start:i-8, i, key:highs[0], key2:Math.min(...lows), kind:'wedge', conf };
  }},
  { name:'Bull Flag', dir:'bull', detect:(c,i)=>{
    if (i<8) return null;
    const f=c.slice(i-4,i+1), p=c.slice(i-8,i-4);
    if (!(p[p.length-1].close>p[0].open*1.005 && f[f.length-1].close<f[0].open)) return null;
    const poleSize = (p[p.length-1].close-p[0].open)/p[0].open;
    const conf = Math.min(82, 60 + Math.round(poleSize*1500));
    return { start:i-8, i, key:Math.max(...f.map(x=>x.high)), key2:Math.min(...f.map(x=>x.low)), kind:'rect', conf };
  }},
  { name:'Bear Flag', dir:'bear', detect:(c,i)=>{
    if (i<8) return null;
    const f=c.slice(i-4,i+1), p=c.slice(i-8,i-4);
    if (!(p[p.length-1].close<p[0].open*0.995 && f[f.length-1].close>f[0].open)) return null;
    const poleSize = Math.abs(p[p.length-1].close-p[0].open)/p[0].open;
    const conf = Math.min(82, 60 + Math.round(poleSize*1500));
    return { start:i-8, i, key:Math.max(...f.map(x=>x.high)), key2:Math.min(...f.map(x=>x.low)), kind:'rect', conf };
  }},
  { name:'Rising Wedge', dir:'bear', detect:(c,i)=>{
    if (i<10) return null;
    const slice=c.slice(i-10,i+1), highs=slice.map(x=>x.high), lows=slice.map(x=>x.low);
    if (!(highs[highs.length-1]>highs[0] && lows[lows.length-1]>lows[0] && (highs[highs.length-1]-lows[lows.length-1])<(highs[0]-lows[0]))) return null;
    const compression = 1 - (highs[highs.length-1]-lows[lows.length-1])/(highs[0]-lows[0]);
    const conf = Math.min(80, 58 + Math.round(compression*40));
    return { start:i-10, i, key:highs[highs.length-1], key2:lows[lows.length-1], kind:'wedge', conf };
  }},
  { name:'Falling Wedge', dir:'bull', detect:(c,i)=>{
    if (i<10) return null;
    const slice=c.slice(i-10,i+1), highs=slice.map(x=>x.high), lows=slice.map(x=>x.low);
    if (!(highs[highs.length-1]<highs[0] && lows[lows.length-1]<lows[0] && (highs[highs.length-1]-lows[lows.length-1])<(highs[0]-lows[0]))) return null;
    const compression = 1 - (highs[highs.length-1]-lows[lows.length-1])/(highs[0]-lows[0]);
    const conf = Math.min(80, 58 + Math.round(compression*40));
    return { start:i-10, i, key:highs[highs.length-1], key2:lows[lows.length-1], kind:'wedge', conf };
  }},
];

function runPatternScanSilent() {
  const cdles = S.candles; if (cdles.length < 20) { S.activePatterns = []; return []; }
  const n = cdles.length, results = [];
  // Scan recent history (last 30 bars) for each pattern, keep the best one per name
  const lookback = Math.min(30, n);
  PATTERNS.forEach(p => {
    let best = null;
    for (let i = n - lookback; i < n; i++) {
      if (i < 15) continue;
      try {
        const r = p.detect(cdles, i);
        if (r && (!best || r.conf > best.conf)) {
          // Translate indices to times so patterns survive S.candles.shift() on long sessions
          best = {
            ...r,
            name:p.name, dir:p.dir, tf:S.tf,
            tStart: cdles[r.start]?.time,
            tEnd: cdles[r.i]?.time,
          };
        }
      } catch(_) {}
    }
    if (best) results.push(best);
  });
  results.sort((a, b) => b.conf - a.conf);
  S.activePatterns = results.slice(0, 5).filter(r => r.conf >= 60);
  return results;
}


