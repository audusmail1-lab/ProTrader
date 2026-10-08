"""
ARIA Copilot, tested in a real browser against protrader_mobile.html:
the chart analysis (TA), ORACLE's plan check, drawings with reasons, the
Learn / Practice modes, chart replay without look-ahead, and live MT5 kept
for the owner only.
   python3 tests/test_copilot_browser.py
"""
import json
import os
import sys

from playwright.sync_api import sync_playwright

sys.path.insert(0, os.path.dirname(__file__))
from test_voice_browser import PROXY, SETUP, serve, typed  # noqa: E402

# A zigzag with a known structure: up, up (two BOS), a lower high, then a drop through the last higher low (CHOCH).
ZIGZAG = """
(() => {
  const pivots = [100, 120, 110, 130, 118, 140, 128, 136, 104, 112], seg = 8, tf = 900;
  const path = [];
  for (let p = 0; p < pivots.length - 1; p++) for (let k = 0; k < seg; k++) path.push(pivots[p] + (pivots[p + 1] - pivots[p]) * k / seg);
  path.push(pivots[pivots.length - 1]);
  const t0 = Math.floor(Date.now() / 1000 / tf) * tf - (path.length + 2) * tf;
  window.__zz = path.map((v, i) => { const n = path[i + 1] ?? v; return { time: t0 + i * tf, open: v, close: n, high: Math.max(v, n) + 0.3, low: Math.min(v, n) - 0.3 }; });
  return window.__zz.length;
})()
"""


def check_ta(page):
    page.evaluate(ZIGZAG)
    r = page.evaluate("""(() => {
      const cd = window.__zz, st = TA.structure(cd);
      return { events: st.events.filter(e => e.type !== 'SWEEP').map(e => [e.type, e.dir, Math.round(e.level)]), trend: st.trend,
               labels: st.swings.map(s => s.label).filter(Boolean), lb: st.lastBreak && [st.lastBreak.type, st.lastBreak.dir] };
    })()""")
    assert r["events"][:2] == [["BOS", "up", 120], ["BOS", "up", 130]], r
    assert r["events"][2:] == [["CHOCH", "down", 128]] and r["trend"] == "down" and r["lb"] == ["CHOCH", "down"], r
    assert "HH" in r["labels"] and "HL" in r["labels"], r
    # causality: the events read from a prefix are exactly the first events of the whole series
    bad = page.evaluate("""(() => {
      const cd = window.__zz, all = JSON.stringify(TA.structure(cd).events.map(e => [e.type, e.i])), bad = [];
      for (let n = 10; n <= cd.length; n++) { const ev = JSON.stringify(TA.structure(cd.slice(0, n)).events.map(e => [e.type, e.i])).slice(0, -1);
        if (!all.startsWith(ev)) bad.push(n); }
      return bad;
    })()""")
    assert bad == [], bad
    # a wick through a swing high that closes back below is a sweep, not a break
    sw = page.evaluate("""(() => {
      const cd = window.__zz.slice(0, 20).map(c => Object.assign({}, c));   // up to just after the first swing high (120)
      const last = cd[cd.length - 1], hi = cd.reduce((a, c) => Math.max(a, c.high), 0);
      cd.push({ time: last.time + 900, open: last.close, high: hi + 3, low: last.close - 0.5, close: last.close });
      const st = TA.structure(cd); return { ev: st.events.map(e => e.type), sweep: !!st.lastSweep };
    })()""")
    assert sw["sweep"] and "BOS" not in sw["ev"], sw
    # the forming candle is never read
    f = page.evaluate("""(() => { const cd = window.__zz, last = cd[cd.length - 1];
      const a = TA.split(cd, '15m', last.time + 100), b = TA.split(cd, '15m', last.time + 900);
      return [a.closed.length, !!a.forming, b.closed.length, !!b.forming]; })()""")
    n = page.evaluate("window.__zz.length")
    assert f == [n - 1, True, n, False], f
    print("ok  TA: swings, BOS/CHOCH, sweeps, no look-ahead, forming candle apart")


def check_oracle(page):
    r = page.evaluate("""(() => {
      const R = TA.read(window.__zz, '15m', 1e12), st = R.structure, atr = R.atr, p = R.price;
      const run = plan => ORACLE.check(Object.assign({ sym: 'R_75', entry: p }, plan), R, null);
      const nostop = run({ side: 'sell', target: p - 10 });
      const wrong = run({ side: 'sell', stop: p - 2, target: p - 10 });
      const counter = run({ side: 'buy', stop: p - atr * 2, target: p + atr * 6 });
      const tight = run({ side: 'sell', stop: p + atr * 0.3, target: p - atr * 3 });
      const sh = st.highAbove;
      const good = run({ side: 'sell', stop: sh.price + atr * 0.3, target: p - (sh.price + atr * 0.3 - p) * 2 });
      const htf = ORACLE.check({ sym: 'R_75', entry: p, side: 'sell', stop: sh.price + atr * 0.3, target: p - (sh.price + atr * 0.3 - p) * 2 }, R, { tf: '4h', trend: 'up' });
      const k = res => res.items.filter(i => i.kind !== 'ok').map(i => i.kind + ':' + i.text.slice(0, 40));
      return { nostop: nostop.status, wrong: wrong.status, counter: [counter.status, k(counter)], tight: [tight.status, k(tight)], good: [good.status, k(good), good.flags], htf: htf.status, trend: st.trend };
    })()""")
    assert r["trend"] == "down", r
    assert r["nostop"] == "INCOMPLETE", r
    assert r["wrong"] == "CONTRADICTED", r
    assert r["counter"][0] == "CONTRADICTED" and any("Counter-trend" in x for x in r["counter"][1]), r
    assert r["tight"][0] == "CONTRADICTED" and any("average candle ranges" in x or "inside normal noise" in x for x in r["tight"][1]), r
    assert r["good"][0] == "SUPPORTED", r
    assert r["good"][2]["stopBeyond"] is True and r["good"][2]["withTrend"] is True and r["good"][2]["rr"] == 2, r
    assert r["htf"] == "CONTRADICTED", r
    print("ok  ORACLE: incomplete, wrong side, counter-trend, stop in noise, supported, higher timeframe")


def check_drawings(page):
    page.evaluate("VOICE.open(false); COPILOT.clear(); DT.removeAll && (DT.state.bySym = {}, DT.state.dm && DT.state.dm.clear())")
    # one drawing of the user's own, which ARIA must never touch
    mine = page.evaluate("DT.manager().add({ kind: 'horizontal-line', points: [{ time: S.candles[200].time, price: 44050 }], name: 'my level' })")
    out = typed(page, "analyze the chart")
    n = page.evaluate("COPILOT.ours().length")
    assert n > 0 and f"I drew {n} objects" in out and "checked" in out, (n, out)
    info = page.evaluate("COPILOT.ours().map(d => ({ id: d.id, label: d.aria && d.aria.label, why: d.aria && d.aria.why, rule: d.aria && d.aria.rule, got: !!DT.manager().get(d.id) }))")
    assert all(d["got"] and d["why"] and len(d["why"]) > 30 and d["rule"] for d in info), info
    assert {d["rule"] for d in info} >= {"structure", "zones", "liquidity"}, info
    # a whole analysis is one undo step (the user's line stays)
    page.evaluate("DT.undo()")
    assert page.evaluate("COPILOT.ours().length") == 0 and page.evaluate(f"!!DT.manager().get({json.dumps(mine)})")
    page.evaluate("DT.redo()")
    assert page.evaluate("COPILOT.ours().length") == n
    info = page.evaluate("COPILOT.ours().map(d => ({ id: d.id, label: d.aria && d.aria.label, why: d.aria && d.aria.why, rule: d.aria && d.aria.rule }))")
    # the reason for the selected drawing
    zone = next(d for d in info if d["rule"] == "zones")
    page.evaluate(f"DT.manager().select([{json.dumps(zone['id'])}])")
    out = typed(page, "why did you draw this")
    assert zone["why"][:60] in out, (out, zone)
    page.evaluate(f"DT.manager().select([{json.dumps(mine)}])")
    out = typed(page, "why did you draw this")
    assert "yours, not mine" in out, out
    page.evaluate("DT.manager().select([])")
    # saved with the reasons, and still there after leaving the market and coming back
    page.wait_for_timeout(500)
    saved = page.evaluate("JSON.parse(localStorage.getItem('protrader.drawings.v1') || '{}')['R_75'] || []")
    assert sum(1 for d in saved if d.get("aria", {}).get("why")) == n, len(saved)
    page.evaluate("selectPair('frxXAUUSD')"); page.wait_for_timeout(300); page.evaluate("selectPair('R_75')"); page.wait_for_timeout(300)
    assert page.evaluate("COPILOT.ours().filter(d => d.aria && d.aria.why).length") == n
    page.evaluate(SETUP)          # switching markets in the test reloads candles the test has to pin again
    # drawing one thing replaces only ARIA's earlier drawing of that thing
    out = typed(page, "draw the fib")
    assert page.evaluate("COPILOT.ours().filter(d => d.aria.rule === 'fib').length") == 1, out
    out = typed(page, "clear aria's drawings")
    assert f"Removed my {n} drawings" in out, out
    assert page.evaluate("COPILOT.ours().length") == 0
    assert page.evaluate(f"!!DT.manager().get({json.dumps(mine)})"), "the user's own drawing was removed"
    print(f"ok  drawings: {n} placed and verified, reasons per drawing, persisted, one undo step, clear leaves the user's own")


def check_parse(page):
    cases = {
        "analyze the chart": "analyze", "analyse gold on the 1 hour": "analyze", "what do you see": "analyze",
        "why did you draw that line": "why", "clear aria's drawings": "clear", "remove your drawings": "clear",
        "what is a choch": "define", "what does liquidity mean": "define", "whats a doji": "define",
        "what's the structure": "topic", "where is the liquidity": "topic", "where is support": "topic",
        "show me the zones": "draw", "draw the fib": "draw", "mark the liquidity": "draw",
        "teach me": "lesson", "teach me fibonacci": "lesson", "quiz me": "quiz", "next lesson": "lesson",
        "check my plan buy stop 43800 target 2 to 1": "plan", "challenge my trade idea": "plan",
        "my decision dna": "dna", "suggest a stop": "suggest_stop", "start replay": "rp_start", "practice mode": "mode",
    }
    for phrase, want in cases.items():
        got = page.evaluate(f"VOICE.parse({json.dumps(phrase)})")
        assert got.get("intent") == want, (phrase, got)
    # the old commands are untouched
    for phrase, want in {"buy gold 1% risk stop 2640": "order", "close the long position": "close", "move my stop to 2650": "move_stop",
                         "should I buy gold": "aria", "what does aria say": "aria", "what's my risk": "risk", "show me vol 75 one second on the 4 hour": "switch",
                         "brief me": "brief", "trend across timeframes": "trend"}.items():
        got = page.evaluate(f"VOICE.parse({json.dumps(phrase)})")
        assert got.get("intent") == want, (phrase, got)
    p = page.evaluate("VOICE.parse('check my plan sell at 44100 stop 44300 target 43600')")
    assert p["side"] == "sell" and p["price"] == 44100 and p["stop"] == {"price": 44300} and p["target"] == {"price": 43600}, p
    print("ok  parse: copilot intents, and every older command still routes the same way")


def check_learn(page):
    page.evaluate("localStorage.removeItem('protrader.learning.v1'); COPILOT.lesson = null; COPILOT.quiz = null")
    out = typed(page, "teach me")
    assert out.startswith("Market structure.") and page.evaluate("COPILOT.mode") == "learn", out
    assert page.evaluate("document.querySelectorAll('#cpPanel .cp-p').length") == 3
    out = typed(page, "show me")
    assert page.evaluate("COPILOT.ours().filter(d => d.aria.rule === 'structure').length") > 0, out
    out = typed(page, "quiz me")
    q = page.evaluate("COPILOT.quiz")
    assert q and len(q["options"]) == 3 and all(o in out for o in q["options"]), (q, out)
    assert page.evaluate("[...document.querySelectorAll('#vxChips .vx-chip')].map(b => b.textContent)") == ["A", "B", "C"]
    out = typed(page, "ABCD"[q["answer"]])
    assert out.startswith("Correct."), out
    rec = page.evaluate("JSON.parse(localStorage.getItem('protrader.learning.v1')).lessons.structure")
    assert rec["right"] == 1 and rec["seen"] >= 1, rec
    assert page.evaluate("document.querySelectorAll('#cpPanel .cp-opt.right').length") == 1
    # a wrong answer is graded wrong and explained
    typed(page, "quiz me")
    q = page.evaluate("COPILOT.quiz")
    out = typed(page, "ABCD"[(q["answer"] + 1) % len(q["options"])])
    assert out.startswith("Not quite") and q["options"][q["answer"]] in out, out
    out = typed(page, "what is a change of character")
    assert out.startswith("Change of character") and page.evaluate("COPILOT.lesson") == "bos", out
    out = typed(page, "next lesson")
    assert out.startswith("Support and resistance."), out
    page.evaluate("COPILOT.lesson = null; COPILOT.quiz = null; COPILOT.renderPanel()")
    assert page.evaluate("document.querySelectorAll('#cpPanel .cp-item.lesson.done').length") == 1
    print("ok  learn: lesson, show me on the chart, quiz graded and saved, glossary, next lesson")


def check_practice(page):
    page.evaluate("localStorage.removeItem('protrader.learning.v1'); TR.positions = []; TR.orders = []; S.trades = []; COPILOT.plan = null; COPILOT.check = null")
    # 44000 sits on the sine chart; its last swing low is about 43840
    out = typed(page, "check my plan buy stop 43900 target 2 to 1")
    c = page.evaluate("COPILOT.check")
    assert c["status"] == "CONTRADICTED" and "ORACLE says contradicted" in out, out
    assert any("swing low" in i["text"] for i in c["items"] if i["kind"] == "against"), c["items"]
    assert page.evaluate("document.querySelector('#cpPanel .cp-oracle.contradicted') !== null")
    out = typed(page, "suggest a stop")
    stop = page.evaluate("COPILOT.plan.stop")
    assert stop < 43840, (stop, out)
    page.evaluate("COPILOT.setPlan('target', COPILOT.rrTarget(COPILOT.plan, 2)); COPILOT.setPlan('reason', 'Bounce from a zone')")
    out = typed(page, "check my plan")
    c = page.evaluate("COPILOT.check")
    assert c["flags"]["stopBeyond"] is True and c["flags"]["rr"] == 2, c
    d = page.evaluate("JSON.parse(localStorage.getItem('protrader.learning.v1')).decisions")
    assert len(d) == 1 and d[0]["reason"] == "Bounce from a zone" and d[0]["flags"]["stopBeyond"] is True, d   # the re-check replaced the first check
    out = typed(page, "place it on paper")
    pend = page.evaluate("VOICE.pending && { title: VOICE.pending.title, rows: VOICE.pending.rows }")
    assert pend and pend["title"].startswith("Practice · Buy") and ["ORACLE", f"{c['status']} · process {page.evaluate('COPILOT.score(COPILOT.check)')}"] in pend["rows"], pend
    typed(page, "confirm")
    pos = page.evaluate("TR.positions.map(p => ({ id: p.id, sl: p.sl, risk0: p.risk0 }))")
    assert len(pos) == 1 and abs(pos[0]["sl"] - stop) < 1e-6, pos
    d = page.evaluate("JSON.parse(localStorage.getItem('protrader.learning.v1')).decisions")
    assert d[-1]["placed"] and d[-1]["pos"] == pos[0]["id"], d
    assert page.evaluate("COPILOT.outcome(COPILOT.load().decisions.slice(-1)[0])") == "open"
    # close it at the stop: the outcome is -1 R, kept apart from the process score
    page.evaluate(f"OT.closePosition({pos[0]['id']}, null, 'Stop loss', {stop})")
    page.wait_for_timeout(200)
    dna = page.evaluate("COPILOT.dna()")
    assert dna["placed"] == 1 and dna["closed"] == 1 and abs(page.evaluate("COPILOT.outcome(COPILOT.load().decisions.slice(-1)[0])") + 1) < 0.02, dna
    out = typed(page, "my decision dna")
    assert "placed 1" in out and "Judge yourself by the process" in out, out
    # with orders going to MT5, practice refuses
    page.evaluate("VOICE._mt5 = VOICE.mt5; VOICE.mt5 = () => true")
    out = typed(page, "check my plan")
    out = typed(page, "place it")
    assert "paper only" in out and not page.evaluate("VOICE.pending"), out
    page.evaluate("VOICE.mt5 = VOICE._mt5")
    print("ok  practice: ORACLE challenges, stop suggestion, decision logged and linked, outcome kept apart, never on MT5")


def check_replay(page):
    page.evaluate("""(() => {
      FEEDX.request = () => Promise.reject(new Error('offline in the test'));
      window.__taMax = 0; window.__taRead = TA.read.bind(TA);
      TA.read = (cd, tf, now) => { if (cd.length) window.__taMax = Math.max(window.__taMax, cd[cd.length - 1].time); return window.__taRead(cd, tf, now); };
      TR.positions = []; TR.orders = []; localStorage.removeItem('protrader.learning.v1');
    })()""")
    page.evaluate("COPILOT.setMode('replay')")
    out = typed(page, "start replay")
    assert page.evaluate("REPLAY.active"), out
    st = page.evaluate("({ cur: REPLAY.cursor(), total: REPLAY.total(), shown: REPLAY.shown(), last: REPLAY.visible().slice(-1)[0].time })")
    assert st["shown"]["n"] == st["cur"] and st["shown"]["last"] == st["last"] and st["cur"] < st["total"], st
    page.evaluate("VOICE.open(false)")
    out = typed(page, "analyze")
    assert page.evaluate("window.__taMax") <= st["last"], "analysis read a candle after the cursor"
    typed(page, "next candle")
    typed(page, "forward 5")
    st2 = page.evaluate("({ cur: REPLAY.cursor(), shown: REPLAY.shown(), src: COPILOT.src().cd.length, last: REPLAY.visible().slice(-1)[0].time })")
    assert st2["cur"] == st["cur"] + 6 and st2["shown"]["n"] == st2["cur"] and st2["src"] == st2["cur"], st2
    out = typed(page, "what's the structure")
    assert page.evaluate("window.__taMax") <= st2["last"], "a question read a candle after the cursor"
    # "buy" inside a replay plans a replay trade: nothing reaches the paper account
    out = typed(page, "buy here")
    assert page.evaluate("REPLAY.planning()") and not page.evaluate("VOICE.pending") and page.evaluate("TR.positions.length") == 0, out
    out = typed(page, "check my plan")
    assert "ORACLE says" in out and page.evaluate("window.__taMax") <= st2["last"], out
    out = typed(page, "take it")
    assert page.evaluate("REPLAY.trading()") and "next candle's open" in out, out
    nxt = page.evaluate("REPLAY.total() > REPLAY.cursor() ? null : null")
    page.evaluate("REPLAY.step(1)")
    fill = page.evaluate("REPLAY.visible().slice(-1)[0].open")
    # walk until the trade ends, or close it by hand
    for _ in range(60):
        if not page.evaluate("REPLAY.trading()"):
            break
        page.evaluate("REPLAY.step(1)")
    if page.evaluate("REPLAY.trading()"):
        page.evaluate("REPLAY.closeTrade()")
    d = page.evaluate("JSON.parse(localStorage.getItem('protrader.learning.v1')).decisions.slice(-1)[0]")
    assert d["source"] == "replay" and d["placed"] and isinstance(d["outcomeR"], (int, float)) and abs(d["entry"] - fill) < 1e-9, d
    assert page.evaluate("document.querySelector('#rpInfo .rp-review') !== null")
    assert page.evaluate("TR.positions.length") == 0
    typed(page, "end replay")
    assert not page.evaluate("REPLAY.active") and page.evaluate("document.getElementById('rpWrap') === null")
    page.evaluate("(() => { TA.read = window.__taRead; })()")
    print(f"ok  replay: cursor-only chart and reads, steps, ORACLE on the past, fill at next open ({d['outcomeR']:+} R), no paper trades, exit")


def check_mt5_gate(browser, port):
    ctx = browser.new_context(viewport={"width": 1280, "height": 860})
    pg = ctx.new_page()
    pg.add_init_script("localStorage.setItem('protrader.mt5bridge.v1', JSON.stringify({ key: 'student-bridge-key-0000', shown: true, symMap: {} }));")
    pg.goto(f"http://127.0.0.1:{port}/protrader_mobile.html", wait_until="domcontentloaded")
    pg.wait_for_function("typeof LIVE !== 'undefined' && typeof ACCOUNT !== 'undefined'")
    pg.wait_for_timeout(800)
    r = pg.evaluate("""(() => { LIVE.route = true; openDeposit();
      const o = { allowed: mt5Allowed(), on: LIVE.on, routing: LIVE.routing(), liveHidden: document.getElementById('acctOptLive').hidden,
                  card: document.getElementById('lvCard') ? document.getElementById('lvCard').style.display : 'none' };
      closeDeposit(); LIVE.goLive(); o.afterGoLive = LIVE.on; return o; })()""")
    assert r == {"allowed": False, "on": False, "routing": False, "liveHidden": True, "card": "none", "afterGoLive": False}, r
    # the owner signs in: the bridge comes back without a reload
    r = pg.evaluate("""(() => { localStorage.setItem('protrader.account.v1', JSON.stringify({ uid: 7, owner: true, v: {}, h: {} })); LIVE.recheck(); openDeposit();
      const o = { allowed: mt5Allowed(), on: LIVE.on, liveHidden: document.getElementById('acctOptLive').hidden }; closeDeposit(); return o; })()""")
    assert r == {"allowed": True, "on": True, "liveHidden": False}, r
    ctx.close()
    # the owner key on a device is enough on its own
    ctx = browser.new_context()
    pg = ctx.new_page()
    pg.add_init_script("localStorage.setItem('protrader.sentinelKey', 'x'); localStorage.setItem('protrader.mt5bridge.v1', JSON.stringify({ key: 'owner-bridge-key-00000', shown: true }));")
    pg.goto(f"http://127.0.0.1:{port}/protrader_mobile.html", wait_until="domcontentloaded")
    pg.wait_for_function("typeof LIVE !== 'undefined'")
    pg.wait_for_timeout(500)
    assert pg.evaluate("mt5Allowed() && LIVE.on"), "owner key should allow MT5"
    ctx.close()
    print("ok  MT5: students and guests are paper only; the owner (key or Academy owner role) keeps MT5")


def shots(browser, port, out_dir):
    if not out_dir:
        return
    for name, vp in (("desktop", {"width": 1280, "height": 860}), ("phone", {"width": 390, "height": 844})):
        ctx = browser.new_context(viewport=vp, device_scale_factor=2 if name == "phone" else 1, is_mobile=name == "phone", has_touch=name == "phone")
        pg = ctx.new_page()
        pg.goto(f"http://127.0.0.1:{port}/protrader_mobile.html", wait_until="domcontentloaded")
        pg.wait_for_function("typeof COPILOT !== 'undefined' && typeof DT !== 'undefined'")
        pg.wait_for_timeout(1500)
        pg.evaluate(SETUP)
        pg.evaluate("CH.setData ? CH.setData(S.candles) : CH.candle.setData(S.candles.map(c => ({ time: c.time, open: c.open, high: c.high, low: c.low, close: c.close })))")
        pg.evaluate("VOICE.open(false)")
        typed(pg, "analyze the chart", 600)
        pg.screenshot(path=os.path.join(out_dir, f"copilot_analyze_{name}.png"))
        typed(pg, "teach me", 300); typed(pg, "quiz me", 300)
        pg.screenshot(path=os.path.join(out_dir, f"copilot_learn_{name}.png"))
        typed(pg, "check my plan buy stop 43900 target 2 to 1", 300)
        pg.evaluate("document.querySelector('#cpPanel').scrollTop = 220")
        pg.screenshot(path=os.path.join(out_dir, f"copilot_practice_{name}.png"))
        pg.evaluate("(() => { FEEDX.request = () => Promise.reject(new Error('offline')); })()")
        typed(pg, "start replay", 300)
        pg.wait_for_function("REPLAY.active")
        pg.evaluate("REPLAY.step(3); REPLAY.analyze(); REPLAY.planFor('sell')")
        pg.wait_for_timeout(400)
        pg.screenshot(path=os.path.join(out_dir, f"copilot_replay_{name}.png"))
        ctx.close()


def main():
    httpd = serve(); port = httpd.server_address[1]
    args = ["--ignore-certificate-errors"] + ([f"--proxy-server={PROXY}", "--proxy-bypass-list=127.0.0.1;localhost;<local>"] if PROXY else [])
    with sync_playwright() as p:
        b = p.chromium.launch(args=args)
        page = b.new_context(viewport={"width": 1280, "height": 860}).new_page()
        errs = []
        page.on("pageerror", lambda e: errs.append(str(e)))
        page.goto(f"http://127.0.0.1:{port}/protrader_mobile.html", wait_until="domcontentloaded")
        page.wait_for_function("typeof COPILOT !== 'undefined' && typeof DT !== 'undefined' && typeof OT !== 'undefined'")
        page.wait_for_timeout(1500)
        page.evaluate(SETUP)
        page.evaluate("CH.setData ? CH.setData(S.candles) : CH.candle.setData(S.candles.map(c => ({ time: c.time, open: c.open, high: c.high, low: c.low, close: c.close })))")
        check_ta(page)
        check_oracle(page)
        check_parse(page)
        check_drawings(page)
        check_learn(page)
        check_practice(page)
        check_replay(page)
        assert not errs, errs
        check_mt5_gate(b, port)
        shots(b, port, os.environ.get("SHOTS", ""))
        b.close()
    httpd.shutdown()
    print("all copilot checks passed")


if __name__ == "__main__":
    main()
