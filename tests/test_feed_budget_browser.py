"""The feed request budget, in a real browser against the Deriv replay server
with Deriv's per-socket limit switched on (220 counted requests a minute):
  1. a cold open plus twenty quick timeframe flips never trips the limit;
  2. when Deriv does refuse (limit lowered to 100), the chart says so, counts
     down, and loads by itself when the minute clears — no reload, no tap;
  3. at the weekend (46 markets shut) the idle-instrument watchdog leaves them
     alone until their opening time, with or without a working order.
   python3 tests/test_feed_budget_browser.py
"""
import functools, http.server, socketserver, threading, os, subprocess, sys, time, json, tempfile
from playwright.sync_api import sync_playwright
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(HERE, '..')
TMP = tempfile.mkdtemp()
P = os.environ.get('HTTPS_PROXY', '')
T0 = {}

def app_html(port):
    html = open(f'{ROOT}/protrader_mobile.html').read().replace("const DERIV_WS_URL = 'wss://api.derivws.com/trading/v1/options/ws/public';", f"const DERIV_WS_URL = 'ws://127.0.0.1:{port}';")
    assert html.count(f'ws://127.0.0.1:{port}') == 1
    return html

class Q(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
    def translate_path(self, path):
        p = path.split('?')[0]
        return f'{TMP}/app.html' if p == '/app.html' else http.server.SimpleHTTPRequestHandler.translate_path(self, path)

def log_rows(path):
    if not os.path.exists(path): return []
    return [json.loads(l) for l in open(path) if l.strip()]

def busiest_minute(rows):
    ts = sorted(r['t'] for r in rows)
    best = 0
    for i, t in enumerate(ts):
        j = i
        while j < len(ts) and ts[j] - t <= 60: j += 1
        best = max(best, j - i)
    return best

def run(name, env, body, viewport=(1280, 800), mobile=False):
    wsport = 18800 + abs(hash(name)) % 100
    log = f'{TMP}/{name}.log'
    open(f'{TMP}/app.html', 'w').write(app_html(wsport))
    h = socketserver.TCPServer(("127.0.0.1", 0), functools.partial(Q, directory=ROOT)); threading.Thread(target=h.serve_forever, daemon=True).start()
    e = dict(os.environ, REPLAY_LOG=log, **env)
    srv = subprocess.Popen([sys.executable, f'{HERE}/deriv_replay_server.py', HERE, str(wsport)], env=e); time.sleep(1.5)
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(args=['--ignore-certificate-errors'] + ([f'--proxy-server={P}', '--proxy-bypass-list=127.0.0.1;localhost;<local>'] if P else []))
            ctx = b.new_context(viewport={'width': viewport[0], 'height': viewport[1]}, device_scale_factor=2, is_mobile=mobile, has_touch=mobile, locale='en-NG', timezone_id='Africa/Lagos')
            pg = ctx.new_page(); errs = []; pg.on('pageerror', lambda x: 'language tag' not in str(x) and errs.append(str(x)))
            pg.route('**/api/**', lambda r: r.fulfill(status=404, body='{}'))
            T0['goto'] = time.time()
            pg.goto(f'http://127.0.0.1:{h.server_address[1]}/app.html', wait_until='domcontentloaded')
            pg.wait_for_function("typeof S!=='undefined' && typeof FEEDQ!=='undefined'")
            body(pg, log)
            assert not errs, errs
            b.close()
    finally:
        srv.terminate(); h.shutdown()

# ── 1. cold open + twenty timeframe flips, under Deriv's real limit ───────────
def scenario_budget(pg, log):
    t0 = T0['goto']
    pg.wait_for_function("S.wsConnected && S.candles.length>0", timeout=20000)
    first_chart = time.time() - t0
    pg.wait_for_function("DAY.st[S.sym] && DAY.st[S.sym].open>0", timeout=10000)
    day_sym = time.time() - t0
    rows = log_rows(log)
    order = [r['type'] + ':' + str(r['sym']) for r in rows[:6]]
    assert rows[0]['type'] == 'ticks_history' and rows[0]['sym'] == pg.evaluate("derivSym(S.sym)"), ('the chart goes first', order)
    assert 'active_symbols:brief' in order[:3] and 'ticks:' + rows[0]['sym'] in order[:3], ('then the instrument list and the live quotes', order)
    pg.wait_for_timeout(3000)
    # twenty-two quick flips, the last one lands on 4h
    tfs = ['1m', '5m', '15m', '1h', '4h', '1d', '1w'] * 3
    pg.evaluate("tfs => { tfs.forEach(tf => setTF(tf)); setTF('4h'); }", tfs)
    pg.wait_for_function("S.tf==='4h' && S.candles.length>0 && S.candles.every(c=>c.time%14400===0)", timeout=20000)
    pg.wait_for_timeout(2000)
    rows = log_rows(log)
    st = pg.evaluate("FEEDQ.status()")
    chart_reqs = [r for r in rows if r['type'] == 'ticks_history' and r['sub'] and r['sym'] == pg.evaluate("derivSym(S.sym)")]
    assert 2 <= len(chart_reqs) <= 6, ('flips in flight collapse into one request each', len(chart_reqs))
    refused = [r for r in rows if r['refused']]
    assert not refused, refused[:3]
    assert st['episodes'] == 0, st
    busiest = busiest_minute(rows)
    assert busiest <= 180, busiest
    assert len(rows) >= 90, ('every instrument was still subscribed', len(rows))
    hidden = pg.evaluate("document.getElementById('chartLoading').hidden")
    assert hidden
    # the live stream follows the chart: the forming 4h bar keeps updating after the flips
    close0 = pg.evaluate("S.candles[S.candles.length-1].close")
    pg.wait_for_function(f"S.tf==='4h' && S.candles[S.candles.length-1].close !== {close0!r}", timeout=20000)
    # a quick flip away and straight back (the stream it wants is still running) lands on a live chart too
    pg.evaluate("setTF('1h'); setTF('4h')")
    pg.wait_for_function("S.tf==='4h' && S.candles.length>0 && document.getElementById('chartLoading').hidden", timeout=20000)
    close1 = pg.evaluate("S.candles[S.candles.length-1].close")
    pg.wait_for_function(f"S.tf==='4h' && S.candles[S.candles.length-1].close !== {close1!r}", timeout=20000)
    sub = pg.evaluate("_histSubId")
    assert sub and sub.endswith('-14400'), ('the one live candle stream is the 4h one', sub)
    print(f'ok  cold open: chart in {first_chart:.1f}s, its daily bar in {day_sym:.1f}s; 22 timeframe flips → {len(chart_reqs) - 1} chart requests, one candle stream, still live; '
          f'busiest minute {busiest} of 220 allowed; refused 0; {len(rows)} requests so far')
    # the lists' daily bars keep trickling in behind, never ahead of the chart
    pg.wait_for_function("Object.keys(DAY.st).length >= 60", timeout=90000)
    rows = log_rows(log)
    assert busiest_minute(rows) <= 180, busiest_minute(rows)
    assert not [r for r in rows if r['refused']]
    print(f'ok  {pg.evaluate("Object.keys(DAY.st).length")} daily bars in after {time.time() - t0:.0f}s, busiest minute {busiest_minute(rows)}, still no refusal')

# ── 2. Deriv refuses: the chart says so and recovers on its own ───────────────
def scenario_refused(pg, log):
    pg.wait_for_function("S.wsConnected && S.candles.length>0", timeout=20000)
    pg.wait_for_function("FEEDQ.status().episodes >= 1", timeout=30000)        # the open burst passes the lowered limit
    pg.evaluate("setTF('4h')")                                                 # a new chart request lands in the held queue
    pg.wait_for_function("!document.getElementById('chartLoading').hidden && /retrying in \\d+ s/.test(document.getElementById('chartLoading').textContent)", timeout=5000)
    text = pg.evaluate("document.getElementById('chartLoading').textContent")
    t0 = time.time()
    pg.wait_for_function("S.tf==='4h' && S.candles.length>0 && document.getElementById('chartLoading').hidden", timeout=75000)
    waited = time.time() - t0
    rows = log_rows(log)
    refused = [r for r in rows if r['refused']]
    st = pg.evaluate("FEEDQ.status()")
    assert refused and st['episodes'] >= 1, (len(refused), st)
    assert waited <= 66, waited
    print(f'ok  refused {len(refused)} (limit lowered to 100): "{text}" → 4h chart loaded by itself after {waited:.0f}s, no reload')

# ── 3. the weekend: shut markets are left alone until they open ───────────────
def scenario_weekend(pg, log):
    pg.wait_for_function("S.wsConnected && S.candles.length>0", timeout=20000)
    pg.wait_for_function("otInfo.frxEURUSD && otInfo.frxEURUSD.closedMsg && otInfo.OTC_FTSE && otInfo.OTC_FTSE.closedMsg", timeout=20000)
    pg.wait_for_timeout(1500)
    info = pg.evaluate("({msg: otInfo.frxEURUSD.closedMsg, reopenAt: otInfo.frxEURUSD.reopenAt, closedAt: otInfo.frxEURUSD.closedAt, now: Date.now()})")
    assert info['reopenAt'] and info['reopenAt'] > info['now'] and info['reopenAt'] - info['now'] < 48 * 3600e3, info
    closed = lambda rows: [r for r in rows if r['type'] == 'ticks' and str(r['sym']).startswith(('frx', 'OTC_', 'WLD'))]
    n0 = len(closed(log_rows(log)))
    assert n0 == 46, n0
    # ten watchdog passes, the ten-second kind and the two-minute kind, with a working order on a shut market
    pg.evaluate("""() => { const o = TR.orders; TR.orders = [{symbol: 'frxEURUSD'}];
      for (let i = 0; i < 10; i++) { OT.resubscribeIdle(true); OT.resubscribeIdle(false); }
      TR.orders = o; }""")
    pg.wait_for_timeout(2000)
    n1 = len(closed(log_rows(log)))
    assert n1 == n0, (n0, n1)
    # an idle OPEN market with a position is still picked up by the ten-second pass (once per pass)
    pg.wait_for_function("derivFresh('R_75', 90000)", timeout=20000)
    r75 = lambda rows: [r for r in rows if r['type'] == 'ticks' and r['sym'] == 'R_75']
    before = len(r75(log_rows(log)))
    pg.evaluate("""() => { const p = TR.positions; TR.positions = [{symbol: 'R_75'}]; otBook.R_75 = {bid: 1, ask: 1, ts: Date.now() - 20000};
      OT.resubscribeIdle(true); TR.positions = p; }""")
    pg.wait_for_timeout(1500)
    rows = log_rows(log)
    assert len(r75(rows)) == before + 1, (before, len(r75(rows)))
    assert not [r for r in rows if r['refused']]
    print(f'ok  weekend: 46 shut markets asked once each (was every 10 s with a working order = {46 * 6}/min); reopen parsed {time.strftime("%a %H:%M UTC", time.gmtime(info["reopenAt"] / 1000))}; '
          f'an idle open market with a position is picked up once; busiest minute {busiest_minute(rows)}')

if __name__ == '__main__':
    run('budget', {'REPLAY_LIMIT': '220'}, scenario_budget)
    run('refused', {'REPLAY_LIMIT': '100'}, scenario_refused)
    run('weekend', {'REPLAY_LIMIT': '220', 'REPLAY_CLOSED': 'frx,OTC_,WLD'}, scenario_weekend)
    print('all feed-budget checks passed')
