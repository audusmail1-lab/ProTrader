"""Replays recorded Deriv traffic to the app at real cadence; answers history/ping/forget.
Optional, through the environment (all off by default):
  REPLAY_LIMIT=220   Deriv's per-socket budget: counted requests (ticks, ticks_history,
                     active_symbols, forget) beyond this within REPLAY_WINDOW seconds of
                     the first one are refused with RateLimit, as the real gateway does
  REPLAY_WINDOW=60   seconds; the window restarts with the first request after it ends
  REPLAY_CLOSED=frx,OTC_,WLD   symbol prefixes whose tick subscription answers MarketIsClosed
  REPLAY_LOG=path    one JSON line per counted request: t, conn, type, sym, refused"""
import asyncio, json, time, sys, random, os
import websockets
SP=sys.argv[1]; PORT=int(sys.argv[2]); SPEED=float(sys.argv[3]) if len(sys.argv)>3 else 1.0
LIMIT=int(os.environ.get("REPLAY_LIMIT") or 0); WINDOW=float(os.environ.get("REPLAY_WINDOW") or 60)
CLOSED=tuple(p for p in (os.environ.get("REPLAY_CLOSED") or "").split(",") if p)
LOG=os.environ.get("REPLAY_LOG")
REC=json.load(open(f"{SP}/fixtures_deriv_replay.json"))
ticks=[(t, json.loads(r)) for t,r in REC if json.loads(r).get("msg_type")=="tick"]
first={}
for _,d in ticks: first.setdefault(d["tick"]["symbol"], float(d["tick"]["quote"]))
conn_seq=0
def reopen_text():
    t=time.gmtime(time.time()+86400); return time.strftime("%Y-%m-%d 00:00:00", t)
async def handler(ws):
    global conn_seq
    conn_seq+=1; conn=conn_seq
    subs={}; t0=time.time(); shift=int(t0)-int(ticks[0][1]["tick"]["epoch"])
    win={"start":0.0,"n":0}
    def echo(d, msg_type):
        rep={"msg_type":msg_type,"echo_req":d}
        if "req_id" in d: rep["req_id"]=d["req_id"]
        if "passthrough" in d: rep["passthrough"]=d["passthrough"]
        return rep
    def counted(d):
        kind=next((k for k in ("ticks_history","ticks","active_symbols","forget_all","forget") if k in d), None)
        if not kind: return None, False
        now=time.time()
        if LIMIT:
            if now-win["start"]>WINDOW: win["start"]=now; win["n"]=0
            win["n"]+=1
            refused=win["n"]>LIMIT
        else: refused=False
        if LOG:
            with open(LOG,"a") as f: f.write(json.dumps({"t":round(now,3),"conn":conn,"type":kind,"sym":d.get(kind) if kind!="forget" else None,"gran":d.get("granularity"),"sub":bool(d.get("subscribe")),"refused":refused})+"\n")
        return kind, refused
    def shut(sym): return bool(CLOSED) and str(sym).startswith(CLOSED)
    async def reader():
        async for raw in ws:
            try: d=json.loads(raw)
            except: continue
            kind, refused=counted(d)
            if refused:
                rep=echo(d, kind); rep["error"]={"code":"RateLimit","message":f"You have reached the rate limit for {kind}."}
                await ws.send(json.dumps(rep)); continue
            if "ticks" in d:
                if shut(d["ticks"]):
                    rep=echo(d, "tick"); rep["error"]={"code":"MarketIsClosed","message":f"This market is presently closed. Market will open at {reopen_text()}."}
                    await ws.send(json.dumps(rep)); continue
                sid=f"sub-{d['ticks']}"; subs[d["ticks"]]=sid
            elif "active_symbols" in d:
                rep=echo(d, "active_symbols")
                rep["active_symbols"]=[{"underlying_symbol":s,"exchange_is_open":0 if shut(s) else 1,"is_trading_suspended":0} for s in first]
                await ws.send(json.dumps(rep))
            elif "ticks_history" in d:
                sym=d["ticks_history"]; g=int(d.get("granularity",60)); n=int(d.get("count",300))
                px=first.get(sym, 100.0); now=int(time.time()); end_s=d.get("end","latest")
                last_t=(now//g)*g if end_s=="latest" else (int(end_s)//g)*g
                start=last_t - g*(n-1)
                trend={60:-1,300:1,900:1,3600:-1,14400:1,86400:1}.get(g,0)*0.00015   # 1m & 1h drift down, others up
                cds=[]; p=px*(1-trend*n)
                rnd=random.Random(g*7+sum(map(ord,sym)))
                for i in range(n):
                    o=p; c=o*(1+trend+rnd.uniform(-0.0004,0.0004)); h=max(o,c)*(1+rnd.uniform(0,0.0003)); l=min(o,c)*(1-rnd.uniform(0,0.0003)); p=c
                    cds.append({"epoch":start+i*g,"open":o,"high":h,"low":l,"close":c})
                if end_s=="latest" and d.get("subscribe"): cds[-1]["close"]=px; cds[-1]["high"]=max(cds[-1]["high"],px); cds[-1]["low"]=min(cds[-1]["low"],px)
                if g==86400: cds[-1].update({"open":px*0.99,"high":px*1.012,"low":px*0.985})
                rep={"msg_type":"candles","echo_req":d,"candles":cds}
                if "req_id" in d: rep["req_id"]=d["req_id"]
                if "passthrough" in d: rep["passthrough"]=d["passthrough"]
                if d.get("subscribe"):
                    # one live candle stream per (symbol, granularity), as on Deriv
                    if any(v[0]==f"hist-{sym}-{g}" for k,v in subs.items() if isinstance(k,tuple)):
                        err=echo(d,"ticks_history"); err["error"]={"code":"AlreadySubscribed","message":f"You are already subscribed to {sym}"}
                        await ws.send(json.dumps(err)); continue
                    rep["subscription"]={"id":f"hist-{sym}-{g}"}; subs[("hist",sym,g)]=(f"hist-{sym}-{g}", g, d)
                await ws.send(json.dumps(rep))
            elif "ping" in d: await ws.send(json.dumps({"msg_type":"ping","ping":"pong"}))
            elif "forget" in d:
                for k,v in list(subs.items()):
                    if isinstance(k,tuple) and v[0]==d["forget"]: del subs[k]
                rep=echo(d,"forget"); rep["forget"]=1; await ws.send(json.dumps(rep))
            elif "forget_all" in d:
                if d["forget_all"] in ("candles", ["candles"]):
                    for k in [k for k in subs if isinstance(k,tuple)]: del subs[k]
                rep=echo(d,"forget_all"); rep["forget_all"]=[]; await ws.send(json.dumps(rep))
    async def writer():
        i=0; bar={}
        while i<len(ticks):
            el=(time.time()-t0)*SPEED
            while i<len(ticks) and ticks[i][0]<=el:
                d=ticks[i][1]; sym=d["tick"]["symbol"]; i+=1
                if shut(sym): continue
                if sym in subs:
                    tk=dict(d["tick"]); tk["epoch"]=int(tk["epoch"])+shift
                    await ws.send(json.dumps({"msg_type":"tick","echo_req":{"ticks":sym,"subscribe":1},"subscription":{"id":subs[sym]},"tick":tk}))
                for k,h in list(subs.items()):
                    if not (isinstance(k,tuple) and k[1]==sym): continue
                    sid,g,req=h; ep=int(d["tick"]["epoch"])+shift; ot=(ep//g)*g; q=float(d["tick"]["quote"])
                    b=bar.get((sym,g))
                    if not b or b["open_time"]!=ot: b={"open_time":ot,"open":q,"high":q,"low":q,"close":q}; bar[(sym,g)]=b
                    b["high"]=max(b["high"],q); b["low"]=min(b["low"],q); b["close"]=q
                    o={"msg_type":"ohlc","echo_req":req,"subscription":{"id":sid},"ohlc":{"symbol":sym,"granularity":g,"open_time":ot,"epoch":ep,"open":b["open"],"high":b["high"],"low":b["low"],"close":b["close"],"id":sid}}
                    if "req_id" in req: o["req_id"]=req["req_id"]
                    await ws.send(json.dumps(o))
            await asyncio.sleep(0.02)
    await asyncio.gather(reader(), writer())
async def main():
    async with websockets.serve(handler, "127.0.0.1", PORT, max_size=2**24):
        await asyncio.Future()
asyncio.run(main())
