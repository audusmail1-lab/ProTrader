/* Independent, closed-bar MTF analysis. No chart/simulator state is accepted. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.ProTraderMTF = api;
})(typeof globalThis === 'object' ? globalThis : this, function () {
  'use strict';
  const intervals = Object.freeze({'1m':60, '5m':300, '15m':900, '1h':3600, '4h':14400});
  const timeframes = Object.keys(intervals), minimumBars = 200;
  const unavailable = (status, message, extra = {}) => ({status, message, ...extra});
  const numeric = n => typeof n === 'number' && Number.isFinite(n);
  function ema(values, period) {
    let value = values[0];
    return values.map(n => (value += (n - value) * 2 / (period + 1)));
  }
  function analyze(candles, tf, asOf = Date.now() / 1000) {
    const seconds = intervals[tf];
    if (!seconds) return unavailable('unsupported', 'Unsupported interval');
    if (!numeric(asOf) || asOf <= 0) return unavailable('unavailable', 'Invalid evidence cutoff');
    if (!Array.isArray(candles) || !candles.length) return unavailable('unavailable', 'No candle history');
    if (candles.length > 5000) return unavailable('unavailable', 'Candle history exceeds the evidence limit');
    // Reject malformed/mixed series rather than repairing time or price evidence.
    for (let i = 0; i < candles.length; i++) {
      const c = candles[i];
      if (!c || !['time','open','high','low','close'].every(k => numeric(c[k])) ||
          c.time <= 0 || !Number.isInteger(c.time) || c.low <= 0 || c.high < Math.max(c.open,c.close,c.low) ||
          c.low > Math.min(c.open,c.close) || (i && c.time <= candles[i-1].time))
        return unavailable('unavailable', 'Invalid candle history');
      // Session gaps may skip whole intervals, but off-grid or finer bars cannot
      // establish this timeframe. Match Oracle's completed-history contract.
      if (i && (c.time - candles[i-1].time < seconds || (c.time - candles[i-1].time) % seconds !== 0))
        return unavailable('unavailable', 'Incorrect candle interval');
    }
    const closed = candles.filter(c => c.time + seconds <= asOf);
    const last = closed[closed.length - 1];
    if (!last || closed.length < minimumBars)
      return unavailable('insufficient', `${closed.length}/${minimumBars} closed bars; more history needed`, {bars:closed.length});
    // Multiples alone also accept a coarse history relabelled as a finer one.
    // Require actual adjacent completed candles at the requested interval;
    // a forming/future bar cannot supply that evidence.
    if (!closed.some((bar, i) => i > 0 && bar.time - closed[i-1].time === seconds))
      return unavailable('unavailable', 'No completed candles establish this interval');
    const closedAt = last.time + seconds;
    if (asOf - closedAt > Math.max(180, seconds * 2))
      return unavailable('stale', 'History stale or market closed', {closedAt, bars:closed.length});
    const closes = closed.map(c => c.close), n = closes.length - 1;
    const fast = ema(closes,20)[n], slow = ema(closes,50)[n];
    const e12 = ema(closes,12), e26 = ema(closes,26);
    const line = e12.map((v,i) => v-e26[i]), signal = ema(line,9)[n];
    let gain = 0, loss = 0;
    for (let i=1; i<=14; i++) { const d=closes[i]-closes[i-1]; gain+=Math.max(d,0)/14; loss+=Math.max(-d,0)/14; }
    for (let i=15; i<=n; i++) { const d=closes[i]-closes[i-1]; gain=(gain*13+Math.max(d,0))/14; loss=(loss*13+Math.max(-d,0))/14; }
    const rsi = gain === 0 && loss === 0 ? 50 : loss === 0 ? 100 : 100-100/(1+gain/loss);
    const window = closed.slice(-14), high=Math.max(...window.map(c=>c.high)), low=Math.min(...window.map(c=>c.low));
    const stoch = high === low ? 50 : (last.close-low)/(high-low)*100;
    const direction = (a,b) => a>b ? 'bull' : a<b ? 'bear' : 'neut';
    return {status:'ready', closedAt, bars:closed.length,
      values:{ema20:fast,ema50:slow,rsi,macd:line[n],signal,stoch},
      directions:[direction(fast,slow),direction(rsi,50),direction(line[n],signal),direction(stoch,50)]};
  }

  // A bounded, per-symbol/provider/interval cache. At most one request runs at a
  // time. Switching context aborts it and guards even adapters ignoring abort.
  function createController({loadRow, onChange, now = Date.now, ttl = 60000}) {
    const cache = new Map();
    let context=null, generation=0, abort=null, running=false, rows={};
    const key = (c,tf) => `${c.provider}:${c.symbol}:${tf}`;
    const emit = () => {
      for (const tf of timeframes) {
        const row=rows[tf];
        if (row && row.status==='ready' && now()/1000-row.closedAt>Math.max(180,intervals[tf]*2))
          rows[tf]=unavailable('stale','History stale or market closed',{closedAt:row.closedAt,bars:row.bars});
      }
      onChange({context, rows:{...rows}});
    };
    function select(next) {
      if (context && context.symbol===next.symbol && context.provider===next.provider) return refresh();
      generation++; if (abort) abort.abort(); running=false;
      context={...next}; rows={};
      for (const tf of timeframes) {
        const cached=cache.get(key(context,tf));
        rows[tf]=cached && now()-cached.fetchedAt < ttl ? cached.row : unavailable('loading','Loading separate history…');
      }
      emit(); return refresh();
    }
    async function refresh() {
      if (!context) return;
      if (running) {emit();return;}
      const seq=generation, current={...context}, cutoff=now()/1000;
      const controller=new AbortController(); abort=controller; running=true;
      try {
        for (const tf of timeframes) {
          if (seq!==generation || controller.signal.aborted) return;
          const cached=cache.get(key(current,tf));
          if (cached && now()-cached.fetchedAt < ttl) {
            // Re-evaluate freshness as wall time passes, even while cached.
            rows[tf]=cached.candles ? analyze(cached.candles,tf,now()/1000) : cached.row;
            continue;
          }
          // Remove old arrows while revalidating; a failed refresh cannot leave
          // the last successful response looking current.
          rows[tf]=unavailable('loading','Refreshing separate history…'); emit();
          let candles, row;
          try {
            candles=await loadRow(current,tf,controller.signal);
            row=analyze(candles,tf,cutoff);
            // A cached forming candle must never become a "closed" candle
            // merely because time passed: its final OHLC was never received.
            if (Array.isArray(candles) && row.status!=='unavailable') candles=candles.filter(c=>c && c.time+intervals[tf]<=cutoff);
            else candles=undefined;
          }
          catch (e) { row=unavailable('unavailable',e && e.message || 'Data request failed'); }
          if (seq!==generation || controller.signal.aborted) return;
          cache.set(key(current,tf),{candles,row,fetchedAt:now()});
          while (cache.size>50) cache.delete(cache.keys().next().value);
          rows[tf]=row; emit();
        }
      } finally { if (seq===generation) {running=false;emit();} }
    }
    function stop(message='Offline — reconnect to refresh') {
      generation++; if(abort) abort.abort(); running=false;
      for (const tf of timeframes) rows[tf]=unavailable('unavailable',message);
      emit();
    }
    return {select,refresh,stop};
  }
  return {intervals,timeframes,minimumBars,analyze,createController};
});
