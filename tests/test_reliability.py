import os,sys,tempfile,time,unittest,asyncio
from unittest.mock import patch
os.environ['SENTINEL_ENABLED']='0'
os.environ['SENTINEL_DB']=os.path.join(tempfile.mkdtemp(),'audit.db')
sys.path.insert(0,os.path.dirname(os.path.dirname(__file__)))
import sentinel as s
import sentinel_core as c

class Reliability(unittest.TestCase):
 def test_htf_closed_warm_fresh_only(self):
  ct=[i*14400 for i in range(1,63)];tr=['up']*61+['down']
  self.assertEqual(c.confirmed_trend(ct,tr,ct[-1]-1),'up')
  self.assertEqual(c.confirmed_trend(ct,tr,ct[-1]),'down')
  self.assertIsNone(c.confirmed_trend(ct,tr,ct[30]))
  self.assertIsNone(c.confirmed_trend(ct,tr,ct[-1]+14431))
  self.assertIsNone(c.confirmed_trend([2,1],['up','down'],2))
 def test_trailing_results_use_net_profit_not_exit_label(self):
  rows=[dict(status='timeout',r=.5,cost_r=.1,closed_at=1,model='7.2c'),dict(status='loss',r=-.05,cost_r=.2,closed_at=2,model='7.2c')]
  result=c.summarise(rows)
  self.assertEqual(result['win_rate'],.5)
  self.assertIsNone(result['breakeven_win_rate'])
  self.assertIsNone(result['p_vs_breakeven'])
 def test_foreign_history_cannot_pollute_owner(self):
  s._meta_set('mt5_channel','owner');s._mt5_state.update(last=0,deals=[])
  s._mt5_track('other',{'positions':[]},[{'ticket':'9','profit':9999}])
  self.assertEqual(s._mt5_state['deals'],[])
 def test_missing_snapshot_not_closed_and_no_guessed_pnl(self):
  s._meta_set('mt5_channel','owner');s._mt5_open.clear();s._mt5_state.update(loaded=True,last=0,deals=[])
  p={'ticket':'77','side':'buy','symbol':'EURUSD','entry':1.1,'price':1.11,'volume':1,'profit':100,'sl':1.09,'time':int(time.time())}
  s._mt5_track('owner',{'positions':[p]},None)
  s._mt5_state['last']=0;s._mt5_track('owner',{},None)
  self.assertIn('mt5:77',s._mt5_open)
  s._mt5_state['last']=0;s._mt5_open['mt5:77']['_gone']=1
  s._mt5_track('owner',{'positions':[]},None)
  r=s._mt5_open['mt5:77'];self.assertIsNone(r['closed']);self.assertNotIn('pnl',r)
  self.assertEqual(r['reconciliation'],'awaiting_deal_history')
 def test_htf_asof_ignores_future_cached_close(self):
  ct=[i*14400 for i in range(1,63)];tr=['up']*61+['down'];m=next(iter(c.MARKETS.values())) if isinstance(c.MARKETS,dict) else c.MARKETS[0]
  s._trend_cache[m.id]=(ct,tr,time.time()+500)
  self.assertEqual(asyncio.run(s._trend_4h(m,ct[-1]-1)),'up')
 def test_partial_history_waits_and_exit_is_volume_weighted(self):
  s._meta_set('mt5_channel','owner');s._mt5_open.clear();s._mt5_state.update(loaded=True,last=0,deals=[])
  p={'ticket':'88','side':'buy','symbol':'EURUSD','entry':100.,'price':101.,'volume':1.,'profit':10,'sl':99.,'time':int(time.time())}
  s._mt5_track('owner',{'positions':[p]},None)
  a={'kind':'trade','ticket':'88','exit':102.,'volume':.25,'profit':5.,'reason':'Manual'}
  b={**a,'exit':101.,'volume':.75,'profit':7.5}
  s._mt5_state['last']=0;s._mt5_track('owner',{'positions':[]},[a])
  self.assertIn('mt5:88',s._mt5_open)
  s._mt5_state['last']=0;s._mt5_track('owner',{'positions':[]},[b,a])
  rec=next(r for r in s._managed_rows() if r['key']=='mt5:88')
  self.assertEqual(rec['exit_r'],1.25)
  self.assertEqual(rec['pnl'],12.5)
  self.assertEqual(rec['reconciliation'],'deal_history_received')
if __name__=='__main__':unittest.main()


class PortedOntoMain(unittest.TestCase):
 """The same fixes, checked against the current main (research loop, live test, twin)."""
 def test_connections_close_after_use(self):
  import sqlite3
  with s._lock, s._db() as con:
   con.execute("SELECT 1").fetchall()
  with self.assertRaises(sqlite3.ProgrammingError):
   con.execute("SELECT 1")
 def test_4h_refresh_once_per_close_overdue_every_10_min_empty_after_a_minute(self):
  m = c.MARKET_BY_ID["frxXAUUSD"]; calls = []
  def series(last_close):
   n = 80; return [{"time": last_close - 14400 * (n - i), "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0 + i * .001} for i in range(n)]
  async def fake(sym, tf, count=0, **k):
   calls.append(sym); return fake.data
  now = time.time()
  with patch.object(c, "fetch_candles", fake):
   fake.data = series(int(now // 14400 * 14400)); s._trend_cache.pop(m.id, None)
   asyncio.run(s._trend_4h(m, int(now)))
   nxt = s._trend_cache[m.id][2]; self.assertAlmostEqual(nxt, int(now // 14400 * 14400) + 14400 + 30, delta=1)
   asyncio.run(s._trend_4h(m, int(now)))
   self.assertEqual(len(calls), 1)                                   # no refetch before the next close
   fake.data = series(int(now // 14400 * 14400) - 3 * 14400); s._trend_cache.pop(m.id, None)
   self.assertIsNone(asyncio.run(s._trend_4h(m, int(now))))          # 12h+ old: a session gap is unavailable, not flat
   self.assertAlmostEqual(s._trend_cache[m.id][2], now + 600, delta=5)
   fake.data = []; s._trend_cache.pop(m.id, None)
   self.assertIsNone(asyncio.run(s._trend_4h(m, int(now))))
   self.assertAlmostEqual(s._trend_cache[m.id][2], now + 60, delta=5)
 def test_unavailable_trend_blocks_and_says_so(self):
  book = c.PaperBook()
  m = c.MARKET_BY_ID["R_50"]
  bars = [{"time": 1_700_000_000 + i * 900, "open": 100 + i * .1, "high": 100.5 + i * .1, "low": 99.5 + i * .1, "close": 100.2 + i * .1} for i in range(c.WINDOW)]
  read, new = book.consider(m, "15m", bars, allow_open=True, trend_4h=None)
  if read["verdict"] in ("QUALIFIED", "EXEC_READY"):
   self.assertEqual(read["block"], "4h data unavailable"); self.assertIsNone(new)
 def test_board_feed_stats_fields(self):
  row = s._board_row(c.MARKET_BY_ID["R_50"], "15m", {"time": 1_700_000_000, "close": 1.0},
                     {"dir": "buy", "score": 8, "gates": [], "mcc": "", "wyckoff": "", "pattern": None, "verdict": "QUALIFIED",
                      "sl": .9, "tp2": 1.2, "elliott": {"label": ""}, "fib_r": None, "trend_4h": None, "block": "4h data unavailable"})
  self.assertEqual(row["htf_status"], "unavailable"); self.assertEqual(row["decision_at"], 1_700_000_900)
  st = s.stats()["model"]
  self.assertEqual((st["model"], st["target_r"], st["breakeven_win_rate"], st["max_bars"]), ("7.2c", None, None, 96))
  f = s.feed(10)
  self.assertIn("current", f); self.assertEqual(f["cohort"]["model"], "7.2c"); self.assertIn("open", f) and self.assertIn("closed", f)
 def test_owner_rebind_resets_tracker_state(self):
  os.environ["SENTINEL_ADMIN_KEY"] = "k" * 32
  s._meta_set("mt5_channel", "a")
  s._mt5_state.update(loaded=True, last=123.0, deals=[{"kind": "trade", "ticket": "1", "profit": 50}], deals_at=5.0)
  class R:
   headers = {"x-sentinel-key": "k" * 32, "x-bridge-key": "b" * 32}
  out = asyncio.run(s.managed_bind(R()))
  self.assertTrue(out["bound"])
  # a new account must not inherit the old account's deal history or its throttle
  self.assertEqual((s._mt5_state["deals"], s._mt5_state["last"], s._mt5_state["loaded"]), ([], 0.0, False))
