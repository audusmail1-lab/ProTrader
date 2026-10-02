"""Market feed, in a real browser against a replay of recorded Deriv traffic:
one source for every chart, loading state instead of invented bars, local-time
axis, real multi-timeframe readings, day stats on the shared socket.
   python3 tests/test_feed_browser.py
Recorded traffic: tests/fixtures_deriv_replay.json (45 s, all 89 instruments)."""
import functools, http.server, socketserver, threading, os, subprocess, sys, time, json
from playwright.sync_api import sync_playwright
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.join(HERE, '..'); SP=os.environ.get('FEED_TMP') or HERE; WSPORT=18767
class Q(http.server.SimpleHTTPRequestHandler):
    def log_message(self,*a): pass
    def translate_path(self, path):
        p=path.split('?')[0]
        return f'{TMP}/perf_app.html' if p=='/perf_app.html' else http.server.SimpleHTTPRequestHandler.translate_path(self, path)
html=open(f'{ROOT}/protrader_mobile.html').read().replace("const DERIV_WS_URL = 'wss://api.derivws.com/trading/v1/options/ws/public';", f"const DERIV_WS_URL = 'ws://127.0.0.1:{WSPORT}';")
assert html.count(f'ws://127.0.0.1:{WSPORT}')==1
html=html.replace("function hideChartLoading() {", "function hideChartLoading() { (window.__seen=window.__seen||[]).push(['hide', S.candles.length]);")
html=html.replace("  if (typeof CH !== 'undefined' && CH.ready) CH.sig = '';\n}", "  if (typeof CH !== 'undefined' && CH.ready) CH.sig = '';\n  (window.__seen=window.__seen||[]).push(['show', S.candles.length, document.getElementById('chartLoading').hidden]);\n}")
assert "push(['show'" in html and "push(['hide'" in html
import tempfile; TMP=tempfile.mkdtemp(); open(f'{TMP}/perf_app.html','w').write(html)
h=socketserver.TCPServer(("127.0.0.1",0), functools.partial(Q, directory=ROOT)); threading.Thread(target=h.serve_forever,daemon=True).start()
srv=subprocess.Popen([sys.executable, f'{HERE}/deriv_replay_server.py', HERE, str(WSPORT)]); time.sleep(1.5)
P=os.environ.get('HTTPS_PROXY','')
api_calls=[]
try:
  with sync_playwright() as p:
    b=p.chromium.launch(args=['--ignore-certificate-errors']+([f'--proxy-server={P}','--proxy-bypass-list=127.0.0.1;localhost;<local>'] if P else []))
    ctx=b.new_context(viewport={'width':390,'height':844},device_scale_factor=2,is_mobile=True,has_touch=True,locale='en-NG',timezone_id='Africa/Lagos')
    pg=ctx.new_page(); errs=[]; pg.on('pageerror', lambda e: 'language tag' not in str(e) and errs.append(str(e)))
    def api(r):
        api_calls.append(r.request.url); r.fulfill(status=404, body='{}')
    pg.route('**/api/**', api)
    pg.goto(f'http://127.0.0.1:{h.server_address[1]}/perf_app.html', wait_until='domcontentloaded')
    pg.wait_for_function("typeof S!=='undefined' && typeof FEEDX!=='undefined'")
    pg.wait_for_function("S.wsConnected && S.candles.length>0", timeout=20000); pg.wait_for_timeout(1500)
    st=pg.evaluate("({n:S.candles.length, aligned:S.candles.every(c=>c.time%(TF_SEC[S.tf]||900)===0), hidden:document.getElementById('chartLoading').hidden, sym:S.sym, tf:S.tf})")
    assert st['n']>=900 and st['aligned'] and st['hidden'], st
    seen=pg.evaluate("__seen"); shows=[x for x in seen if x[0]=='show']; hides=[x for x in seen if x[0]=='hide']
    assert shows and all(x[1]==0 and x[2] is False for x in shows) and hides and all(x[1]>0 for x in hides), seen
    assert pg.evaluate("S.candles.every(c=>!c.vol)"), 'invented volume'

    print('ok  loading state until Deriv answers; 1,000 aligned bars; no fake candles', st['sym'], st['tf'])
    # 2. forex charts come from Deriv, not /api/chart
    pg.evaluate("selectPair('frxEURUSD')"); pg.wait_for_function("S.sym==='frxEURUSD' && S.candles.length>900", timeout=15000); pg.wait_for_timeout(2500)
    assert not any('/api/chart' in u or '/api/stream' in u or '/api/quotes' in u for u in api_calls), api_calls
    q=pg.evaluate("({src:pairPrices.frxEURUSD.src, live:pairPrices.frxEURUSD.live, badge:document.getElementById('wsBadge').textContent, last:S.candles[S.candles.length-1].close, px:pairPrices.frxEURUSD.price})")
    assert q['src']=='Deriv' and q['badge']=='LIVE' and abs(q['last']-q['px'])<1e-9, q
    print('ok  EUR/USD chart + price from Deriv only (no Yahoo calls)', q)
    # 3. day stats: header % and top High/Low from the daily bar
    pg.wait_for_function("DAY.st.frxEURUSD && DAY.st.frxEURUSD.open>0", timeout=10000); pg.wait_for_timeout(300)
    d=pg.evaluate("({open:DAY.st.frxEURUSD.open, hi:DAY.st.frxEURUSD.high, lo:DAY.st.frxEURUSD.low, px:pairPrices.frxEURUSD.price, chg:pairPrices.frxEURUSD.chg, topH:+document.getElementById('topH').textContent, topL:+document.getElementById('topL').textContent, hdr:document.getElementById('liveChg').textContent})")
    assert abs(d['chg']-(d['px']-d['open'])/d['open']*100)<1e-6 and abs(d['topH']-max(d['hi'],d['px']))<1e-4 and abs(d['topL']-min(d['lo'],d['px']))<1e-4, d
    assert d['hdr'].startswith('+') and abs(float(d['hdr'].rstrip('%'))-d['chg'])<0.001, d
    print('ok  day open/high/low on the main socket; one % change definition', d['hdr'])
    # 4. local-time axis and the clock agree; UTC toggle
    lbl=pg.evaluate("[TZ.tick(S.candles[S.candles.length-1].time,3), new Date(S.candles[S.candles.length-1].time*1000).toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit'}), document.getElementById('updateTs').textContent.slice(0,5)]")
    assert lbl[0]==lbl[1] and lbl[2]=='Local', lbl
    pg.evaluate("TZ.toggle()"); pg.wait_for_timeout(300)
    lbl2=pg.evaluate("[TZ.tick(S.candles[S.candles.length-1].time,3), new Date(S.candles[S.candles.length-1].time*1000).toUTCString().slice(17,22), document.getElementById('updateTs').textContent.slice(0,3)]")
    assert lbl2[0]==lbl2[1] and lbl2[2]=='UTC', lbl2
    pg.evaluate("TZ.toggle()")
    print('ok  axis in local time (Lagos), tap the clock for UTC', lbl, lbl2)
    # 5. real MTF: rows differ because the replay feeds different trends per timeframe
    pg.evaluate("openMobilePanel('mtf'); setRTab('mtf', document.querySelector('.rtab[data-tab=mtf]'))")
    pg.wait_for_function("MTF.data.frxEURUSD && Object.keys(MTF.data.frxEURUSD).length===5", timeout=15000); pg.wait_for_timeout(400)
    rows=pg.evaluate("[...document.querySelectorAll('#mtf-panel .mtf-row-el')].map(r=>[...r.querySelectorAll('.mtf-cell')].map(c=>c.textContent.trim()))")
    ema={r[0].split(' ')[0]:r[1] for r in rows}
    assert ema['1M']=='▼' and ema['5M']=='▲' and ema['1H']=='▼' and ema['4H']=='▲', ema
    print('ok  Timeframes tab reads each timeframe from its own candles', ema)
    # 6. back-scroll pages older bars through the shared socket
    n0=pg.evaluate("S.candles.length"); pg.evaluate("CH.loadOlder()"); pg.wait_for_function(f"S.candles.length>{n0}+500", timeout=15000)
    print('ok  older history paged on the main socket:', n0, '->', pg.evaluate("S.candles.length"))
    # 7. a symbol switch shows loading, then the new series; nothing random
    pg.evaluate("__seen.length=0; selectPair('R_75')")
    pg.wait_for_function("S.sym==='R_75' && S.candles.length>900", timeout=15000)
    seen=pg.evaluate("__seen"); assert seen[0][0]=='show' and seen[0][1]==0 and seen[0][2] is False and seen[-1][0]=='hide', seen
    print('ok  switching instruments: empty + loading until Deriv answers')
    pg.wait_for_timeout(1500)
    pg.screenshot(path=os.path.join(TMP, 'feed_final.png'))
    assert not errs, errs
    print('all feed checks passed')
finally:
  srv.terminate(); h.shutdown()
