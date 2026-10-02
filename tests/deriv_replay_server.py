"""Replays recorded Deriv traffic to the app at real cadence; answers history/ping/forget."""
import asyncio, json, time, sys, random
import websockets
SP=sys.argv[1]; PORT=int(sys.argv[2]); SPEED=float(sys.argv[3]) if len(sys.argv)>3 else 1.0
REC=json.load(open(f"{SP}/fixtures_deriv_replay.json"))
ticks=[(t, json.loads(r)) for t,r in REC if json.loads(r).get("msg_type")=="tick"]
first={}
for _,d in ticks: first.setdefault(d["tick"]["symbol"], float(d["tick"]["quote"]))
async def handler(ws):
    subs={}; t0=time.time(); shift=int(t0)-int(ticks[0][1]["tick"]["epoch"])
    async def reader():
        async for raw in ws:
            try: d=json.loads(raw)
            except: continue
            if "ticks" in d:
                sid=f"sub-{d['ticks']}"; subs[d["ticks"]]=sid
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
                if d.get("subscribe"): rep["subscription"]={"id":f"hist-{sym}-{g}"}; subs[("hist",sym)]=(f"hist-{sym}-{g}", g, d)
                await ws.send(json.dumps(rep))
            elif "ping" in d: await ws.send(json.dumps({"msg_type":"ping","ping":"pong"}))
            elif "forget" in d: await ws.send(json.dumps({"msg_type":"forget","forget":1}))
    async def writer():
        i=0; bar={}
        while i<len(ticks):
            el=(time.time()-t0)*SPEED
            while i<len(ticks) and ticks[i][0]<=el:
                d=ticks[i][1]; sym=d["tick"]["symbol"]; i+=1
                if sym in subs:
                    tk=dict(d["tick"]); tk["epoch"]=int(tk["epoch"])+shift
                    await ws.send(json.dumps({"msg_type":"tick","echo_req":{"ticks":sym,"subscribe":1},"subscription":{"id":subs[sym]},"tick":tk}))
                h=subs.get(("hist",sym))
                if h:
                    sid,g,req=h; ep=int(d["tick"]["epoch"])+shift; ot=(ep//g)*g; q=float(d["tick"]["quote"])
                    b=bar.get(sym)
                    if not b or b["open_time"]!=ot: b={"open_time":ot,"open":q,"high":q,"low":q,"close":q}; bar[sym]=b
                    b["high"]=max(b["high"],q); b["low"]=min(b["low"],q); b["close"]=q
                    await ws.send(json.dumps({"msg_type":"ohlc","echo_req":req,"subscription":{"id":sid},"ohlc":{"symbol":sym,"granularity":g,"open_time":ot,"epoch":ep,"open":b["open"],"high":b["high"],"low":b["low"],"close":b["close"],"id":sid}}))
            await asyncio.sleep(0.02)
    await asyncio.gather(reader(), writer())
async def main():
    async with websockets.serve(handler, "127.0.0.1", PORT, max_size=2**24):
        await asyncio.Future()
asyncio.run(main())
