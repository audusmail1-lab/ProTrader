// The feed request budget (FEEDQ) and the request/reply helper (FEEDX) on top
// of it, with a fake socket and a fake clock.
//   node --test tests/feed-budget.test.cjs
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync(require('node:path').join(__dirname, '../protrader_mobile.html'), 'utf8');
const start = html.indexOf('const FEEDQ = (() => {');
const end = html.indexOf('/* Day open / high / low per instrument');
assert.ok(start > 0 && end > start, 'FEEDQ/FEEDX source located');
const source = html.slice(start, end);

/* A clock the test moves by hand; timers fire when the clock passes them. */
function clock() {
  let now = 1_000_000, seq = 0; const timers = new Map();
  const add = (fn, ms, every) => { const id = ++seq; timers.set(id, {at: now + Math.max(0, ms || 0), fn, every: every ? Math.max(1, ms) : 0}); return id; };
  return {
    now: () => now,
    setTimeout: (fn, ms) => add(fn, ms, false), setInterval: (fn, ms) => add(fn, ms, true),
    clearTimeout: id => timers.delete(id), clearInterval: id => timers.delete(id),
    advance(ms) {
      const target = now + ms;
      for (;;) {
        let next = null;
        for (const [id, t] of timers) if (t.at <= target && (!next || t.at < next[1].at)) next = [id, t];
        if (!next) break;
        now = Math.max(now, next[1].at);
        if (next[1].every) next[1].at = now + next[1].every; else timers.delete(next[0]);
        next[1].fn();
      }
      now = target;
    },
  };
}
function setup(storeInit = {}) {
  const c = clock();
  const sock = {readyState: 1, out: [], send(s) { this.out.push(JSON.parse(s)); }};
  const store = Object.assign({}, storeInit);
  const ctx = vm.createContext({
    ws: sock, WebSocket: {OPEN: 1}, console,
    localStorage: {getItem: k => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); }},
    Date: {now: c.now}, setTimeout: c.setTimeout, setInterval: c.setInterval, clearTimeout: c.clearTimeout, clearInterval: c.clearInterval,
  });
  vm.runInContext(source + ';globalThis.Q = FEEDQ; globalThis.X = FEEDX;', ctx);
  return {Q: ctx.Q, X: ctx.X, sock, c, ctx, store};
}
const types = sock => sock.out.map(m => m.ticks_history ? 'h' : m.ticks ? 't' : m.forget ? 'f' : m.ping ? 'p' : m.active_symbols ? 'a' : '?');

test('with room, a request leaves at once; when waiting, priority decides the order, not arrival', () => {
  const {Q, sock, c} = setup();
  Q.send({ticks: 'now'}, 4);
  assert.equal(sock.out.length, 1);
  for (let i = 0; i < 179; i++) Q.send({ticks: 't' + i}, 1);             // the minute is spent
  Q.send({ticks: 'A'}, 3); Q.send({ticks_history: 'D', granularity: 86400}, 4); Q.send({ticks_history: 'C', subscribe: 1}, 0); Q.send({ticks: 'F'}, 2);
  assert.equal(sock.out.length, 180);
  c.advance(62_000);
  assert.deepEqual(sock.out.slice(180).map(m => m.ticks || m.ticks_history), ['C', 'F', 'A', 'D']);
});

test('the cap: 180 a minute, the two lowest priorities stop 40 short of it and go at two a second', () => {
  const {Q, sock, c} = setup();
  for (let i = 0; i < 190; i++) Q.send({ticks: 't' + i}, 3);
  assert.equal(sock.out.length, 2, 'list work leaves at two a second, not in a burst');
  c.advance(1_100);
  assert.equal(sock.out.length, 4);
  c.advance(30_000);
  assert.ok(sock.out.length >= 56 && sock.out.length <= 66, 'about two a second: ' + sock.out.length);
  c.advance(90_000);
  assert.equal(sock.out.length, 190, 'at two a second the window frees as fast as it fills: all 190 went, never more than ~122 in any minute');
  assert.ok(Q.status().used <= 125, 'in the window now: ' + Q.status().used);
  for (let i = 0; i < 60; i++) Q.send({ticks_history: 'h' + i, subscribe: 1}, 0);
  assert.equal(sock.out.length, 250, 'the chart is not paced: all 60 at once, inside the cap');
  // a true burst of list work still meets the cap − reserve
  const {Q: Q2, sock: s2, c: c2} = setup();
  for (let i = 0; i < 400; i++) Q2.send({ticks: 'u' + i}, 3);
  c2.advance(58_000);
  assert.ok(s2.out.length >= 110 && s2.out.length <= 118, 'two a second for 58 s: ' + s2.out.length);
  c2.advance(20_000);
  assert.ok(Q2.status().used <= 140, 'never above cap − reserve in a window: ' + Q2.status().used);
});

test('ping is not counted; forget is', () => {
  const {Q, sock} = setup();
  for (let i = 0; i < 179; i++) Q.send({forget: 'id' + i}, 0);
  Q.send({ping: 1}); Q.send({ping: 1});
  assert.equal(sock.out.filter(m => m.ping).length, 2);
  Q.send({ticks_history: 'x', subscribe: 1}, 0);
  assert.equal(types(sock).filter(t => t === 'h').length, 1, '179 forgets + 1 history = 180');
  Q.send({ticks_history: 'y', subscribe: 1}, 0);
  assert.equal(types(sock).filter(t => t === 'h').length, 1, 'the 181st waits');
});

test('keys: a queued twin is kept or replaced; wanted() drops stale requests before they leave', () => {
  const {Q, sock, c} = setup();
  for (let i = 0; i < 180; i++) Q.send({ticks: 't' + i}, 1);          // fill the minute
  assert.equal(Q.send({ticks_history: 'R_75', granularity: 900, subscribe: 1}, 0, {key: 'chart', replace: true}), true);
  assert.equal(Q.send({ticks: 'R_75', subscribe: 1}, 1, {key: 'ticks:R_75'}), true);
  assert.equal(Q.send({ticks: 'R_75', subscribe: 1}, 1, {key: 'ticks:R_75'}), 'twin');
  for (let i = 0; i < 12; i++) Q.send({ticks_history: 'R_75', granularity: 60 * (i + 1), subscribe: 1}, 0, {key: 'chart', replace: true});
  assert.equal(Q.status().queued, 2, 'twelve timeframe flips queued one chart request');
  let want = false;
  Q.send({ticks_history: 'old', subscribe: 1}, 0, {key: 'stale', wanted: () => want});
  c.advance(62_000);
  const h = sock.out.filter(m => m.ticks_history);
  assert.equal(h.length, 1, 'only the last timeframe left; the stale one was dropped');
  assert.equal(h[0].granularity, 720);
  assert.equal(sock.out.filter(m => m.ticks === 'R_75').length, 1);
});

test('a refusal holds the queue until the minute clears, then sends the refused request again', () => {
  const {Q, sock, c} = setup();
  const sentAt = [];
  Q.send({ticks_history: 'R_25', granularity: 14400, subscribe: 1}, 0, {key: 'chart', onSent: () => sentAt.push(c.now())});
  for (let i = 0; i < 70; i++) Q.send({ticks: 't' + i}, 1);           // enough of our own in the window for the refusal to be ours
  const first = sock.out[0];
  assert.ok(first.req_id >= 1000000, 'the budget tags its requests so a refusal can find them');
  c.advance(5_000);
  assert.equal(Q.refused({req_id: first.req_id, error: {code: 'RateLimit'}}), true);
  Q.refused({req_id: 424242, error: {code: 'RateLimit'}}); Q.refused({req_id: 424243, error: {code: 'RateLimit'}});
  const st = Q.status();
  assert.equal(st.limitedUntil, c.now() - 5_000 + 62_500, 'held until the oldest send is a minute old; a burst of refusals is one episode');
  assert.equal(st.episodes, 1); assert.equal(st.strikes, 1);
  Q.send({ticks: 'X'}, 1);
  assert.equal(sock.out.length, 71, 'nothing leaves while Deriv is refusing');
  c.advance(st.limitedUntil - c.now() + 200);
  assert.equal(sock.out.length, 73);
  assert.equal(sock.out[71].req_id, first.req_id, 'the chart request went again, first, same id');
  assert.equal(sock.out[72].ticks, 'X');
  assert.deepEqual(sentAt.length, 2);
});

test('a refused request is dropped when a newer twin is queued, when no longer wanted, or after four tries', () => {
  const {Q, sock, c} = setup();
  Q.send({ticks_history: 'A', granularity: 60, subscribe: 1}, 0, {key: 'chart'});
  for (let i = 0; i < 179; i++) Q.send({ticks: 't' + i}, 1);                      // uses the rest of the minute
  Q.send({ticks_history: 'A', granularity: 300, subscribe: 1}, 0, {key: 'chart', replace: true});   // waits
  assert.equal(Q.refused({req_id: sock.out[0].req_id, error: {code: 'RateLimit'}}), false, 'a newer chart request is already waiting');
  c.advance(63_000);
  assert.equal(sock.out.filter(m => m.ticks_history).length, 2);
  assert.equal(sock.out[sock.out.length - 1].granularity, 300);
  // four refusals and it is given up
  const {Q: Q2, sock: s2, c: c2} = setup();
  Q2.send({ticks: 'B'}, 1);
  let id = s2.out[0].req_id, n = 1;
  for (let i = 0; i < 4; i++) {
    const again = Q2.refused({req_id: id, error: {code: 'RateLimit'}});
    c2.advance(63_000);
    if (again) { n++; assert.equal(s2.out.length, n); id = s2.out[n - 1].req_id; }
    else assert.equal(i, 3, 'given up on the fourth refusal');
  }
  assert.equal(s2.out.length, 4);
});

test('FEEDX: the timeout runs from the send, a RateLimit keeps the promise waiting, and the reply resolves it', async () => {
  const {Q, X, sock, c} = setup();
  for (let i = 0; i < 180; i++) Q.send({ticks: 't' + i}, 1);           // the minute is spent
  let done = null;
  const p = X.request({ticks_history: 'R_50', count: 2, granularity: 86400, style: 'candles'}, 10_000, 4).then(r => { done = r; }, e => { done = e; });
  c.advance(30_000);
  assert.equal(done, null, 'queued, not timed out: the timeout has not started');
  c.advance(32_000);
  const sentReq = sock.out[sock.out.length - 1];
  assert.equal(sentReq.ticks_history, 'R_50'); assert.deepEqual(sentReq.passthrough, {fx: 1});
  assert.equal(X.route({req_id: sentReq.req_id, passthrough: {fx: 1}, error: {code: 'RateLimit', message: 'You have reached the rate limit for ticks_history.'}}), true);
  await Promise.resolve();
  assert.equal(done, null, 'a refusal is not an answer: the request waits out the hold');
  c.advance(16_000);                                                   // little of ours in the window: a short hold
  const again = sock.out[sock.out.length - 1];
  assert.equal(again.req_id, sentReq.req_id);
  assert.equal(X.route({req_id: again.req_id, passthrough: {fx: 1}, msg_type: 'candles', candles: [{epoch: 1}]}), true);
  await Promise.resolve();
  assert.deepEqual(JSON.parse(JSON.stringify(done.candles)), [{epoch: 1}]);
  // a second request with the same key while one is queued is refused at once, never left hanging
  for (let i = 0; i < 180; i++) Q.send({ticks: 'u' + i}, 1);
  let a = null, b = null;
  X.request({ticks_history: 'K'}, 5000, 4, {key: 'day:K'}).then(() => {}, e => { a = e.message; });
  X.request({ticks_history: 'K'}, 5000, 4, {key: 'day:K'}).then(() => {}, e => { b = e.message; });
  await Promise.resolve();
  assert.equal(a, null); assert.equal(b, 'already requested');
  // and once sent, it times out from the send
  c.advance(62_000); c.advance(5_100);
  await Promise.resolve();
  assert.equal(a, 'feed timeout');
});

test('reset forgets the queue but not the count: a reconnect is no fresh budget', () => {
  const {Q, sock, c} = setup();
  for (let i = 0; i < 200; i++) Q.send({ticks: 't' + i}, 1);
  assert.equal(Q.status().queued, 20);
  Q.reset();
  assert.equal(Q.status().queued, 0); assert.equal(Q.status().used, 180);
  Q.send({ticks: 'fresh'}, 1);
  assert.equal(sock.out.length, 180, 'still full for the rest of the minute');
  c.advance(62_000);
  assert.equal(sock.out[sock.out.length - 1].ticks, 'fresh');
});

test('the cap learns from a refusal and is remembered on the device for six hours', () => {
  const {Q, sock, c, store} = setup();
  for (let i = 0; i < 150; i++) Q.send({ticks: 't' + i}, 1);
  Q.refused({req_id: sock.out[10].req_id, error: {code: 'RateLimit'}});
  assert.equal(Q.status().cap, 140, 'ten under what was in the window when Deriv refused');
  const saved = JSON.parse(store['protrader.feedcap.v1']);
  assert.equal(saved.cap, 140); assert.equal(saved.at, c.now());
  // the next open starts from the learned cap; a stale one is ignored
  assert.equal(setup({'protrader.feedcap.v1': JSON.stringify({cap: 140, at: c.now() - 3600_000})}).Q.status().cap, 140);
  assert.equal(setup({'protrader.feedcap.v1': JSON.stringify({cap: 140, at: c.now() - 2 * 86400_000})}).Q.status().cap, 180);
  assert.equal(setup({'protrader.feedcap.v1': JSON.stringify({cap: 20, at: c.now()})}).Q.status().cap, 180, 'never below the floor');
  // a refusal with little in the window teaches nothing (not this socket's doing), and the floor holds
  const {Q: Q2, sock: s2} = setup();
  for (let i = 0; i < 30; i++) Q2.send({ticks: 'u' + i}, 1);
  Q2.refused({req_id: s2.out[0].req_id, error: {code: 'RateLimit'}});
  assert.equal(Q2.status().cap, 180);
});

test('serial: a second chart request waits for Deriv to answer the first, and goes when it does (or after 20 s unanswered)', () => {
  const {Q, sock, c} = setup();
  Q.send({ticks_history: 'R_75', granularity: 60, subscribe: 1}, 0, {key: 'chart', replace: true, serial: true});
  Q.send({ticks_history: 'R_75', granularity: 300, subscribe: 1}, 0, {key: 'chart', replace: true, serial: true});
  Q.send({ticks_history: 'R_75', granularity: 14400, subscribe: 1}, 0, {key: 'chart', replace: true, serial: true});
  Q.send({ticks: 'R_50'}, 3);
  assert.deepEqual(sock.out.map(m => m.ticks_history ? m.granularity : m.ticks), [60, 'R_50'], 'one chart request in flight; other work is not held up');
  assert.equal(Q.status().queued, 1);
  Q.ack(999);                                                   // some other reply
  assert.equal(sock.out.length, 2);
  Q.ack(sock.out[0].req_id);                                    // Deriv answered the 1m request
  assert.equal(sock.out.length, 3); assert.equal(sock.out[2].granularity, 14400, 'the last flip, not the middle one');
  Q.send({ticks_history: 'R_75', granularity: 900, subscribe: 1}, 0, {key: 'chart', replace: true, serial: true});
  assert.equal(sock.out.length, 3, 'blocked behind the unanswered 4h request');
  c.advance(20_200);
  assert.equal(sock.out.length, 4, 'an unanswered request stops blocking after 20 s');
  // a refusal frees the key too
  const {Q: Q2, sock: s2} = setup();
  Q2.send({ticks_history: 'A', granularity: 60, subscribe: 1}, 0, {key: 'chart', replace: true, serial: true});
  Q2.send({ticks_history: 'A', granularity: 300, subscribe: 1}, 0, {key: 'chart', replace: true, serial: true});
  assert.equal(Q2.refused({req_id: s2.out[0].req_id, error: {code: 'RateLimit'}}), false, 'the refused one is dropped: a newer flip is waiting');
  assert.ok(Q2.status().limitedUntil > 0);
});

test('a refusal with little of our own in the window is another device\'s doing: a short hold, longer each time', () => {
  const {Q, sock, c} = setup();
  for (let i = 0; i < 20; i++) Q.send({ticks: 't' + i}, 1);
  Q.refused({req_id: sock.out[5].req_id, error: {code: 'RateLimit'}});
  assert.equal(Q.status().limitedUntil, c.now() + 15_000, 'fifteen seconds, not a minute');
  assert.equal(Q.status().cap, 180, 'and nothing learned from it');
  c.advance(16_000);
  Q.send({ticks: 'again'}, 1);
  assert.equal(sock.out[sock.out.length - 1].ticks, 'again');
  Q.refused({req_id: sock.out[sock.out.length - 1].req_id, error: {code: 'RateLimit'}});
  assert.equal(Q.status().limitedUntil, c.now() + 30_000, 'twice as long the second time');
  assert.equal(Q.status().strikes, 2);
});

test('inline application JavaScript parses', () => {
  for (const script of html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)) new vm.Script(script[1]);
});
