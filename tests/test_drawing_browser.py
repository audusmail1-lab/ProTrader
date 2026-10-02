"""Drawing tools in a real browser: TradingView's tool set on our chart.
   python3 tests/test_drawing_browser.py
Placement by clicks and by drag, magnet, floating toolbar, undo/redo, lock,
hide all, measure, text, per-symbol saving, the old format's migration, the
position tool's link to the ticket, keyboard shortcuts, and the phone sheet.
Market data: tests/deriv_replay_server.py replays recorded Deriv traffic."""
import functools, http.server, socketserver, threading, os, subprocess, sys, time, json, tempfile
from playwright.sync_api import sync_playwright
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(HERE, '..'); WSPORT = 18768
class Q(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
    def translate_path(self, path):
        p = path.split('?')[0]
        return f'{TMP}/app.html' if p == '/app.html' else http.server.SimpleHTTPRequestHandler.translate_path(self, path)
html = open(f'{ROOT}/protrader_mobile.html').read().replace("const DERIV_WS_URL = 'wss://api.derivws.com/trading/v1/options/ws/public';", f"const DERIV_WS_URL = 'ws://127.0.0.1:{WSPORT}';")
assert html.count(f'ws://127.0.0.1:{WSPORT}') == 1
TMP = tempfile.mkdtemp(); open(f'{TMP}/app.html', 'w').write(html)
h = socketserver.TCPServer(("127.0.0.1", 0), functools.partial(Q, directory=ROOT)); threading.Thread(target=h.serve_forever, daemon=True).start()
srv = subprocess.Popen([sys.executable, f'{HERE}/deriv_replay_server.py', HERE, str(WSPORT)]); time.sleep(1.5)
P = os.environ.get('HTTPS_PROXY', '')
URL = f'http://127.0.0.1:{h.server_address[1]}/app.html'
OLD = {"R_75": [{"id": 3, "type": "hline", "color": "#F59E0B", "pts": [{"t": 0, "p": 0}], "name": "Mirror", "locked": True},
               {"id": 4, "type": "trend", "pts": [{"t": 0, "p": 0}, {"t": 0, "p": 0}], "style": "dashed", "width": 2},
               {"id": 5, "type": "long", "riskBudget": 250, "pts": [{"t": 0, "p": 0}, {"t": 0, "p": 0}, {"t": 0, "p": 0}, {"t": 0, "p": 0}]}]}


def chart_box(pg):
    return pg.evaluate("(() => { const r = CH.chart.chartElement().getBoundingClientRect(); return {x: r.x, y: r.y, w: r.width, h: r.height}; })()")


def xy(pg, i, price):
    """screen point of bar i (from the end when negative) at a price"""
    x, y, ok = pg.evaluate("([i, p]) => { const b = S.candles.at(i); const r = CH.chart.chartElement().getBoundingClientRect(); const x = CH.chart.timeScale().timeToCoordinate(b.time), y = CH.candle.priceToCoordinate(p); return [x == null ? null : r.x + x, y == null ? null : r.y + y, x != null && y != null && x > 0 && x < r.width - 70 && y > 0 && y < r.height - 30]; }", [i, price])
    assert ok, f'bar {i} at {price} is off screen ({x}, {y})'
    return x, y


def bar(pg, i):
    return pg.evaluate("i => S.candles.at(i)", i)


def ready(pg):
    pg.wait_for_function("typeof DT !== 'undefined' && DT.manager() && S.wsConnected && S.candles.length > 200", timeout=25000)
    pg.wait_for_timeout(600)


def desktop(b):
    ctx = b.new_context(viewport={'width': 1280, 'height': 800}, locale='en-NG', timezone_id='Africa/Lagos')
    pg = ctx.new_page(); errs = []; pg.on('pageerror', lambda e: 'language tag' not in str(e) and errs.append(str(e)))
    pg.route('**/api/**', lambda r: r.fulfill(status=404, body='{}'))
    # drawings in the old format, saved by the previous engine, wait in this browser
    pg.add_init_script(f"if (!localStorage.getItem('protrader.drawings.v1')) localStorage.setItem('protrader.drawings.v1', {json.dumps(json.dumps(OLD))});")
    pg.goto(URL, wait_until='domcontentloaded'); ready(pg)
    return ctx, pg, errs


def main():
    with sync_playwright() as p:
        b = p.chromium.launch(args=['--ignore-certificate-errors'] + ([f'--proxy-server={P}', '--proxy-bypass-list=127.0.0.1;localhost;<local>'] if P else []))
        ctx, pg, errs = desktop(b)
        # 0. the old engine's drawings came through: times were 0 so the price-only ones still load
        st = pg.evaluate("({sym: S.sym, bar: !document.getElementById('dtBar').hidden, groups: [...document.querySelectorAll('#dtBar .dt-group')].length, dropdown: !!document.querySelector('details#chartTools'), tools: DT.GROUPS.reduce((n, g) => n + g.tools.length, 0)})")
        assert st['bar'] and st['groups'] == 6 and not st['dropdown'] and st['tools'] >= 80, st
        print('ok  left tools bar with TradingView groups,', st['tools'], 'tools; the dropdown is gone')
        pg.evaluate("selectPair('R_75')"); pg.wait_for_function("S.sym === 'R_75' && S.candles.length > 200", timeout=20000); pg.wait_for_timeout(500)
        mig = pg.evaluate("DT.drawings().map(d => ({kind: d.kind, name: d.name, locked: !!d.locked, style: d.style.lineStyle, w: d.style.width, rb: d.riskBudget, n: d.points.length}))")
        kinds = {m['kind']: m for m in mig}
        assert kinds['horizontal-line']['name'] == 'Mirror' and kinds['horizontal-line']['locked'] and kinds['trend-line']['style'] == 'dashed' and kinds['trend-line']['w'] == 2 and kinds['long-position']['rb'] == 250, mig
        raw = json.loads(pg.evaluate("localStorage.getItem('protrader.drawings.v1')"))
        assert all('kind' in d and 'points' in d for d in raw['R_75']), raw
        print('ok  drawings saved by the old engine migrated: line, dashed trend, long plan with its budget')
        pg.evaluate("DT.removeAll = async () => {}; DT.manager().clear(); DT.state.bySym = {}; localStorage.removeItem('protrader.drawings.v1')"); pg.wait_for_timeout(100)

        # 1. trend line: group button -> flyout -> tool -> two clicks; weak magnet snaps to the candle
        pg.click('#dtBar [data-group="lines"]'); pg.wait_for_selector('.dt-flyout'); pg.click('.dt-flyout [data-kind="trend-line"]')
        assert pg.evaluate("DT.manager().tool()") == 'trend-line'
        assert pg.evaluate("!document.getElementById('dtFloat').hidden && document.querySelector('#dtFloat .dt-armed').textContent.includes('Trend line')")
        lo = bar(pg, -60)['low']; hi = bar(pg, -20)['high']
        x1, y1 = xy(pg, -60, lo - lo * 0.0004); x2, y2 = xy(pg, -20, hi + hi * 0.0004)
        pg.mouse.click(x1, y1); pg.wait_for_timeout(60); pg.mouse.move(x2, y2); pg.wait_for_timeout(60); pg.mouse.click(x2, y2); pg.wait_for_timeout(150)
        d = pg.evaluate("DT.drawings()")
        assert len(d) == 1 and d[0]['kind'] == 'trend-line' and abs(d[0]['points'][0]['price'] - lo) < 1e-9 and abs(d[0]['points'][1]['price'] - hi) < 1e-9, d
        assert pg.evaluate("DT.manager().tool()") is None and pg.evaluate("DT.manager().selection().length") == 1
        saved = json.loads(pg.evaluate("localStorage.getItem('protrader.drawings.v1') || '{}'"))
        pg.wait_for_timeout(400); saved = json.loads(pg.evaluate("localStorage.getItem('protrader.drawings.v1')"))
        assert saved['R_75'][0]['kind'] == 'trend-line', saved
        print('ok  trend line by two clicks, weak magnet snapped both ends to the candles, tool disarmed, saved per symbol')

        # 2. floating toolbar: colour + width, then undo/redo
        assert pg.evaluate("!document.getElementById('dtFloat').hidden && document.querySelector('#dtFloat .dt-ftitle').textContent") == 'Trend line'
        pg.click('#dtFloat [aria-label="Colour and opacity"]'); pg.wait_for_selector('.dt-colors'); pg.click('.dt-colors .dt-sw[title="#f23645"]')
        pg.fill('.dt-colors input[type=range]', '50'); pg.dispatch_event('.dt-colors input[type=range]', 'input'); pg.dispatch_event('.dt-colors input[type=range]', 'change')
        pg.click('#dtFloat [aria-label="Line width"]'); pg.wait_for_selector('.dt-pop'); pg.click('.dt-pop .dt-pop-item:nth-child(3)')
        s = pg.evaluate("({c: DT.drawings()[0].style.color, w: DT.drawings()[0].style.width, past: DT.state.past.length})")
        assert s['c'] == 'rgba(242, 54, 69, 0.5)' and s['w'] == 3 and s['past'] == 4, s     # placed, colour, opacity, width
        pg.click('#dtBar [data-id="undo"]'); pg.click('#dtBar [data-id="undo"]')
        s2 = pg.evaluate("({c: DT.drawings()[0].style.color, w: DT.drawings()[0].style.width})")
        assert s2['w'] == 2 and s2['c'] == '#f23645', s2
        pg.keyboard.press('Control+z'); pg.wait_for_timeout(50)
        assert pg.evaluate("DT.drawings()[0].style.color") == '#2962ff'
        pg.keyboard.press('Control+y'); pg.wait_for_timeout(50)
        assert pg.evaluate("DT.drawings()[0].style.color") == '#f23645'
        print('ok  floating toolbar: colour with opacity, width; undo/redo per step (buttons and Ctrl+Z / Ctrl+Y)')

        # 3. drag a rectangle (press-move-release), then move it by its body; the chart does not pan
        pg.evaluate("DT.arm('rectangle')")
        ax, ay = xy(pg, -55, bar(pg, -55)['high']); bx, by = xy(pg, -25, bar(pg, -25)['low'])
        pg.mouse.move(ax, ay); pg.mouse.down(); pg.mouse.move(bx, by, steps=8); pg.mouse.up(); pg.wait_for_timeout(150)
        r = [d for d in pg.evaluate("DT.drawings()") if d['kind'] == 'rectangle']
        assert len(r) == 1 and r[0]['points'][0]['time'] != r[0]['points'][1]['time'], r
        rng0 = pg.evaluate("CH.chart.timeScale().getVisibleLogicalRange()")
        pts0 = r[0]['points']; mx, my = (ax + bx) / 2, (ay + by) / 2
        pg.mouse.move(mx, my); pg.mouse.down(); pg.mouse.move(mx - 60, my + 20, steps=6); pg.mouse.up(); pg.wait_for_timeout(100)
        r2 = [d for d in pg.evaluate("DT.drawings()") if d['kind'] == 'rectangle'][0]
        rng1 = pg.evaluate("CH.chart.timeScale().getVisibleLogicalRange()")
        assert r2['points'][0]['time'] < pts0[0]['time'] and abs(rng1['from'] - rng0['from']) < 0.01, (r2, rng0, rng1)
        print('ok  rectangle drawn with one drag; moved by its body without panning the chart')

        # 4. lock: no drag, no Delete; unlock via Objects
        pg.click('#dtFloat [aria-label="Lock"]'); pg.wait_for_timeout(50)
        assert pg.evaluate("DT.drawings().find(d => d.kind === 'rectangle').locked")
        pg.mouse.move(mx - 60, my + 20); pg.mouse.down(); pg.mouse.move(mx, my, steps=6); pg.mouse.up(); pg.wait_for_timeout(80)
        pg.keyboard.press('Delete'); pg.wait_for_timeout(50)
        r3 = pg.evaluate("DT.drawings().find(d => d.kind === 'rectangle')")
        assert r3 and r3['points'] == r2['points'], r3
        pg.click('#dtBar [data-id="objects"]'); pg.wait_for_selector('dialog.ws-dialog')
        rows = pg.evaluate("[...document.querySelectorAll('dialog .ws-object .ws-object-name')].map(b => b.textContent)")
        assert rows == ['Trend line', 'Rectangle'], rows
        pg.click('dialog .ws-object:nth-child(2) [data-lock]'); pg.click('dialog header button')
        assert not pg.evaluate("DT.drawings().find(d => d.kind === 'rectangle').locked")
        print('ok  locked: no drag, no Delete; Objects lists both and unlocks')

        # 5. hide all keeps the drawings; show all brings them back; remove all with undo
        pg.keyboard.press('Control+Alt+h'); pg.wait_for_timeout(80)
        assert pg.evaluate("DT.manager().drawings().length") == 0 and pg.evaluate("DT.state.bySym.R_75.length") == 2
        pg.click('#dtBar [data-id="hideall"]'); pg.wait_for_timeout(80)
        assert pg.evaluate("DT.manager().drawings().length") == 2
        print('ok  hide all / show all (Ctrl+Alt+H and the eye)')

        # 6. per-symbol: another instrument starts empty; coming back restores; a reload restores
        pg.evaluate("selectPair('frxEURUSD')"); pg.wait_for_function("S.sym === 'frxEURUSD' && S.candles.length > 200", timeout=20000); pg.wait_for_timeout(300)
        assert pg.evaluate("DT.drawings().length") == 0
        pg.evaluate("selectPair('R_75')"); pg.wait_for_function("S.sym === 'R_75' && S.candles.length > 200", timeout=20000); pg.wait_for_timeout(300)
        assert pg.evaluate("DT.drawings().map(d => d.kind)") == ['trend-line', 'rectangle']
        pg.reload(wait_until='domcontentloaded'); ready(pg)
        pg.evaluate("selectPair('R_75')"); pg.wait_for_function("S.sym === 'R_75' && S.candles.length > 200", timeout=20000); pg.wait_for_timeout(300)
        assert pg.evaluate("DT.drawings().map(d => d.kind)") == ['trend-line', 'rectangle']
        print('ok  drawings stay with their instrument and survive a reload')

        # 7. measure: Shift+click, click -> a range that is not saved and goes on the next click
        n = pg.evaluate("DT.drawings().length")
        p1 = xy(pg, -30, bar(pg, -30)['low']); p2 = xy(pg, -10, bar(pg, -10)['high'])
        pg.keyboard.down('Shift'); pg.mouse.click(*p1); pg.keyboard.up('Shift'); pg.wait_for_timeout(60); pg.mouse.move(*p2); pg.mouse.click(*p2); pg.wait_for_timeout(120)
        m = pg.evaluate("({n: DT.manager().drawings().length, kinds: DT.manager().drawings().map(d => d.kind), saved: (DT.state.bySym.R_75 || []).length})")
        assert m['n'] == n + 1 and 'date-and-price-range' in m['kinds'] and m['saved'] == n, m
        e = xy(pg, -70, bar(pg, -70)['close']); pg.mouse.click(*e); pg.wait_for_timeout(120)
        assert pg.evaluate("DT.manager().drawings().length") == n, 'measure should vanish on the next click'
        print('ok  measure (Shift+click): temporary, never saved')

        # 8. text: one click places it and opens the editor; Enter keeps the text
        pg.keyboard.press('Escape'); pg.evaluate("DT.arm('text')"); t = xy(pg, -50, bar(pg, -50)['high'])
        pg.mouse.click(*t); pg.wait_for_function("document.activeElement && document.activeElement.id === 'dtText'"); pg.keyboard.type('Mirror level'); pg.keyboard.press('Enter'); pg.wait_for_timeout(100)
        tx = pg.evaluate("DT.drawings().find(d => d.kind === 'text')")
        assert tx and tx['text'] == 'Mirror level' and not pg.query_selector('#dtText'), tx
        pg.evaluate("DT.arm('text')"); pg.mouse.click(t[0] + 80, t[1]); pg.wait_for_function("document.activeElement && document.activeElement.id === 'dtText'"); pg.keyboard.press('Escape'); pg.wait_for_timeout(80)
        assert pg.evaluate("DT.drawings().filter(d => d.kind === 'text').length") == 1, 'an empty text is dropped'
        print('ok  text tool: type and Enter; Esc on an empty one removes it')

        # 9. long position: one click, the estimate strip, the budget, Use in ticket
        pg.evaluate("DT.arm('long-position')"); e = xy(pg, -15, bar(pg, -15)['close']); pg.mouse.click(*e); pg.wait_for_timeout(150)
        lp = pg.evaluate("DT.drawings().find(d => d.kind === 'long-position')")
        assert lp and lp['riskBudget'] and not pg.evaluate("document.getElementById('positionMeasure').hidden"), lp
        pg.fill('#positionRisk', '120'); pg.dispatch_event('#positionRisk', 'input'); pg.wait_for_timeout(80)
        stats = pg.evaluate("DT.positionStats(DT.drawings().find(d => d.kind === 'long-position'))")
        assert stats['budget'] == 120 and stats['sl'] < stats['entry'] < stats['tp'] and stats['lots'] is not None, stats
        lbl = pg.evaluate("document.getElementById('positionMeasureStats').textContent")
        assert 'Risk' in lbl and 'R:R' in lbl, lbl
        pg.click('#dtFloat [aria-label="Use in ticket"]'); pg.wait_for_timeout(200)
        tk = pg.evaluate("({sl: TK.sl, tp: TK.tp, side: TK.side})")
        assert tk['side'] == 'buy' and abs(tk['sl'] - stats['sl']) < 1e-3 and abs(tk['tp'] - stats['tp']) < 1e-3, (tk, stats)
        print('ok  long position: budget-sized estimate strip; Use in ticket carries stop and target', {k: round(v, 2) for k, v in tk.items() if isinstance(v, float)})

        # 10. shortcuts and settings dialog
        pg.keyboard.press('Escape'); pg.keyboard.press('Alt+h')
        assert pg.evaluate("DT.manager().tool()") == 'horizontal-line'
        pg.keyboard.press('Escape'); assert pg.evaluate("DT.manager().tool()") is None
        tl = pg.evaluate("DT.drawings().find(d => d.kind === 'trend-line').id")
        pg.evaluate("id => DT.openSettings(id)", tl); pg.wait_for_selector('dialog.ws-dialog')
        tabs = pg.evaluate("[...document.querySelectorAll('dialog .ws-tabs button')].map(b => b.textContent)")
        assert tabs == ['Style', 'Text', 'Coordinates', 'Visibility'], tabs
        pg.check('dialog [data-k="extendRight"]'); pg.click('dialog [data-t="vi"]'); pg.uncheck('dialog [data-u="days"]'); pg.click('dialog [data-done]'); pg.wait_for_timeout(80)
        t2 = pg.evaluate("id => DT.manager().get(id)", tl)
        assert t2['style']['extendRight'] is True and t2['visibility']['days']['on'] is False, t2
        print('ok  Alt+H arms a horizontal line; settings dialog: Style / Text / Coordinates / Visibility')
        assert not errs, errs
        ctx.close()

        # 11. the phone: Draw opens the sheet, a tap arms, two taps draw, the floating toolbar removes
        ctx = b.new_context(viewport={'width': 390, 'height': 844}, device_scale_factor=2, is_mobile=True, has_touch=True, locale='en-NG', timezone_id='Africa/Lagos')
        pg = ctx.new_page(); errs = []; pg.on('pageerror', lambda e: 'language tag' not in str(e) and errs.append(str(e)))
        pg.route('**/api/**', lambda r: r.fulfill(status=404, body='{}'))
        pg.goto(URL, wait_until='domcontentloaded'); ready(pg)
        assert pg.evaluate("document.getElementById('dtBar').hidden || getComputedStyle(document.getElementById('dtBar')).display === 'none'")
        pg.tap('#chartTools'); pg.wait_for_selector('#dtSheet'); pg.tap('#dtSheet .dt-sheet-tabs [data-id="lines"]'); pg.tap('#dtSheet [data-kind="trend-line"]')
        assert pg.evaluate("DT.manager().tool()") == 'trend-line' and not pg.query_selector('#dtSheet')
        p1 = xy(pg, -40, bar(pg, -40)['low']); p2 = xy(pg, -10, bar(pg, -10)['high'])
        pg.touchscreen.tap(*p1); pg.wait_for_timeout(80); pg.touchscreen.tap(*p2); pg.wait_for_timeout(150)
        assert pg.evaluate("DT.drawings().map(d => d.kind)") == ['trend-line']
        assert pg.evaluate("!document.getElementById('dtFloat').hidden")
        pg.tap('#dtFloat [aria-label="Remove (Del)"]'); pg.wait_for_timeout(80)
        assert pg.evaluate("DT.drawings().length") == 0
        pg.tap('#chartTools'); pg.tap('#dtSheet .dt-sheet-tabs [data-id="shapes"]'); pg.tap('#dtSheet [data-kind="rectangle"]')
        pg.touchscreen.tap(*p1); pg.wait_for_timeout(80); pg.touchscreen.tap(*p2); pg.wait_for_timeout(150)
        assert pg.evaluate("DT.drawings().map(d => d.kind)") == ['rectangle']
        pg.screenshot(path=os.path.join(TMP, 'drawing_phone.png'))
        print('ok  phone: Draw sheet, tap to arm, tap-tap to draw, floating toolbar to remove')
        assert not errs, errs
        print('all drawing checks passed  (screens in', TMP + ')')
        b.close()


if __name__ == '__main__':
    try:
        main()
    finally:
        srv.terminate()
