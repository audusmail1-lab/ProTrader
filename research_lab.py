"""
Sentinel research lab — frozen rule sets ("versions") run over the same bars
the scanner sees, in replay and forward, with the evaluation rules written
down in research/docs/03-design.md:

  * a version is a rules dict (see INCUMBENT_RULES); its id is a hash of the
    canonical JSON, so the same rules always get the same id and any change
    is a new version;
  * ResearchBook runs ARIA (sentinel_engine, unchanged) or a Donchian entry
    through optional gates (session window, cost cap, ADX, autocorrelation,
    gate ablation) and the 7.2c exit or research exits (ATR ratchet trail,
    counter-channel, fixed R);
  * replay() runs a version over the cached one-year history exactly as
    sentinel_replay does for the incumbent: closed bars only, 4h trend read
    at the bar's close, one position per market x timeframe, stop first;
  * experiment() produces development / validation / holdout numbers, cost
    sensitivity (x1, x1.5, x2), the placebo (permutation) test for filters,
    and a parameter neighbourhood table; everything is returned as data and
    stored by sentinel_research.record_experiment().

    python research_lab.py fetch                 # cache one year of Deriv history (research/history)
    python research_lab.py run H1                # run the experiment spec research/experiments/H1.json
    python research_lab.py baseline              # incumbent 7.2c over the cache (parity with sentinel_replay)

No part of this file places orders or touches the live scanner's journal.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import random
import sys
import time
from collections import deque
from concurrent.futures import ProcessPoolExecutor
from typing import Any, Optional

import sentinel_core as core
import sentinel_engine as eng

HERE = os.path.dirname(os.path.abspath(__file__))
HISTORY_DIR = os.path.join(HERE, "research", "history")
EXPERIMENTS_DIR = os.path.join(HERE, "research", "experiments")
FOCUS = ["frxNAS100", "frxXAUUSD", "cryBTCUSD", "frxEURUSD", "frxGBPUSD", "frxUSDJPY", "R_75", "1HZ75V"]
PAGES = {"15m": 40, "1h": 10, "4h": 3}

# ── Versions ─────────────────────────────────────────────────────────────────

INCUMBENT_RULES = {
    "entry": "aria",          # aria | donchian
    "model": "7.2c",          # exit/filter model from sentinel_core.MODELS for ARIA entries
    "mtf": None,              # None = the model's setting; True/False overrides the 4h-trend filter
    "wave5_veto": None,       # same for the Wave-5 veto
    "gates": {},              # session | cost_cap | adx | acf | require_gates | drop_gates
    "stop": {"kind": "aria"},  # aria | {"kind": "atr", "mult": 2.0, "period": 20}
    "exit": {"kind": "model"},  # model | atr_trail | channel | fixed_r
    "donchian": {"lookback": 20, "trend": True, "sides": "both"},
    "shadows": False,         # research books do not run the incumbent's shadow exits unless asked
}


def normalize(rules: Optional[dict]) -> dict:
    out = json.loads(json.dumps(INCUMBENT_RULES))
    for k, v in (rules or {}).items():
        if k not in out:
            raise ValueError(f"unknown rule key {k!r}")
        if isinstance(out[k], dict) and isinstance(v, dict) and k != "gates":
            out[k].update(v)
        else:
            out[k] = v
    if out["model"] not in core.MODELS:
        raise ValueError(f"unknown model {out['model']!r}")
    if out["entry"] not in ("aria", "donchian"):
        raise ValueError(f"unknown entry {out['entry']!r}")
    for g in out["gates"]:
        if g not in ("session", "cost_cap", "adx", "acf", "require_gates", "drop_gates"):
            raise ValueError(f"unknown gate {g!r}")
    return out


def rules_id(rules: dict) -> str:
    """Stable id of a rule set: same rules → same id; any change → new id."""
    s = json.dumps(normalize(rules), sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(s.encode()).hexdigest()[:10]


# ── Indicators (closed bars only; the last bar is the bar being judged) ──────

def wilder_atr(bars: list[dict], p: int = 20) -> list[Optional[float]]:
    out: list[Optional[float]] = []
    prev = None
    for i, b in enumerate(bars):
        tr = b["high"] - b["low"] if i == 0 else max(b["high"] - b["low"], abs(b["high"] - bars[i - 1]["close"]),
                                                     abs(b["low"] - bars[i - 1]["close"]))
        if i < p - 1:
            out.append(None)
            continue
        if prev is None:
            prev = sum((bars[j]["high"] - bars[j]["low"]) if j == 0 else
                       max(bars[j]["high"] - bars[j]["low"], abs(bars[j]["high"] - bars[j - 1]["close"]),
                           abs(bars[j]["low"] - bars[j - 1]["close"])) for j in range(i - p + 1, i + 1)) / p
        else:
            prev = (prev * (p - 1) + tr) / p
        out.append(prev)
    return out


def adx(bars: list[dict], p: int = 14) -> tuple[list[Optional[float]], list[Optional[float]], list[Optional[float]]]:
    """Wilder's ADX with +DI/-DI, smoothed the classic way. Returns (adx, +di, -di)."""
    n = len(bars)
    adx_v: list[Optional[float]] = [None] * n
    pdi_v: list[Optional[float]] = [None] * n
    mdi_v: list[Optional[float]] = [None] * n
    if n < 2 * p + 1:
        return adx_v, pdi_v, mdi_v
    trs, pdm, mdm = [0.0], [0.0], [0.0]
    for i in range(1, n):
        h, l, pc = bars[i]["high"], bars[i]["low"], bars[i - 1]["close"]
        up, dn = h - bars[i - 1]["high"], bars[i - 1]["low"] - l
        pdm.append(up if up > dn and up > 0 else 0.0)
        mdm.append(dn if dn > up and dn > 0 else 0.0)
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    s_tr, s_p, s_m = sum(trs[1:p + 1]), sum(pdm[1:p + 1]), sum(mdm[1:p + 1])
    dx_hist: list[float] = []
    adx_prev = None
    for i in range(p, n):
        if i > p:
            s_tr = s_tr - s_tr / p + trs[i]
            s_p = s_p - s_p / p + pdm[i]
            s_m = s_m - s_m / p + mdm[i]
        if s_tr <= 0:
            continue
        pdi, mdi = 100 * s_p / s_tr, 100 * s_m / s_tr
        pdi_v[i], mdi_v[i] = pdi, mdi
        dx = 100 * abs(pdi - mdi) / (pdi + mdi) if (pdi + mdi) > 0 else 0.0
        dx_hist.append(dx)
        if len(dx_hist) == p:
            adx_prev = sum(dx_hist) / p
            adx_v[i] = adx_prev
        elif len(dx_hist) > p:
            adx_prev = (adx_prev * (p - 1) + dx) / p
            adx_v[i] = adx_prev
    return adx_v, pdi_v, mdi_v


def acf1(closes: list[float], n: int = 100) -> Optional[float]:
    """Lag-1 Pearson autocorrelation of log returns over the last n closed bars."""
    c = closes[-(n + 1):]
    if len(c) < 20:
        return None
    r = [math.log(c[i] / c[i - 1]) for i in range(1, len(c)) if c[i - 1] > 0 and c[i] > 0]
    if len(r) < 20:
        return None
    a, b = r[:-1], r[1:]
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if va <= 0 or vb <= 0:
        return None
    return cov / math.sqrt(va * vb)


def utc_hour_frac(epoch: int) -> float:
    t = time.gmtime(epoch)
    return t.tm_hour + t.tm_min / 60


def session_ok(windows: Optional[dict], market: str, close_epoch: int) -> bool:
    """windows: {market: [[start_hour, end_hour], ...]} in UTC decimal hours;
    a market without an entry (or an empty list) is unrestricted (a control)."""
    if not windows:
        return True
    spans = windows.get(market)
    if not spans:
        return True
    h = utc_hour_frac(close_epoch)
    for a, b in spans:
        if a <= b and a <= h < b:
            return True
        if a > b and (h >= a or h < b):       # window across midnight
            return True
    return False


# ── Research book ────────────────────────────────────────────────────────────

class ResearchBook(core.PaperBook):
    """A PaperBook that runs one frozen rule set. Same conventions as the
    incumbent: closed bars, one position per market x timeframe, stop first.
    Research exits and the Donchian entry live here; ARIA itself is untouched."""

    def __init__(self, rules: Optional[dict] = None, news_week: bool = False):
        self.rules = normalize(rules)
        super().__init__(news_week=news_week, model=self.rules["model"])
        self.version = rules_id(self.rules)
        self.meta: dict[str, dict] = {}            # trade id → research annotations (atr at entry, gate readings)
        self.hist: dict[tuple[str, str], deque] = {}
        self._hist_last: dict[tuple[str, str], int] = {}

    # — history for the channel exit —
    def _push_hist(self, market: str, tf: str, bars: list[dict]) -> None:
        key = (market, tf)
        n = max(int(self.rules["exit"].get("channel", 10)), 2) + 1
        dq = self.hist.setdefault(key, deque(maxlen=n))
        last = self._hist_last.get(key, 0)
        for b in bars:
            if b["time"] > last:
                dq.append(b)
                last = b["time"]
        self._hist_last[key] = last

    # — gate readings for a read —
    def annotate(self, m: core.Market, tf: str, window: list[dict], read: dict) -> dict:
        g = self.rules["gates"]
        last = window[-1]
        ann: dict[str, Any] = {"close": last["time"] + core.TF_SEC[tf]}
        if "session" in g:
            ann["session_ok"] = session_ok(g["session"], m.id, ann["close"])
        ann["cost_r"] = round(core.spread_for(m, read["entry"]) / read["sl_dist"], 4) if read.get("sl_dist") else None
        if "adx" in g:
            p = int(g["adx"].get("period", 14))
            a, pdi, mdi = adx(window[-(4 * p + 5):], p)
            ann["adx"] = round(a[-1], 2) if a[-1] is not None else None
            ann["adx_prev"] = round(a[-2], 2) if len(a) > 1 and a[-2] is not None else None
            ann["di_ok"] = (None if pdi[-1] is None else
                            (pdi[-1] > mdi[-1]) if read["dir"] == "buy" else (mdi[-1] > pdi[-1]))
        if "acf" in g:
            ann["acf1"] = acf1([b["close"] for b in window], int(g["acf"].get("n", 100)))
        return ann

    def gates_pass(self, ann: dict, read: dict) -> Optional[str]:
        """None when every gate passes, else the reason the entry is skipped."""
        g = {k: c for k, c in self.rules["gates"].items() if not (isinstance(c, dict) and c.get("readings_only"))}
        if "session" in g and not ann.get("session_ok", True):
            return "outside session"
        if "cost_cap" in g and (ann.get("cost_r") is None or ann["cost_r"] > float(g["cost_cap"])):
            return "cost above cap"
        if "adx" in g:
            cfg = g["adx"]
            if ann.get("adx") is None or ann["adx"] < float(cfg.get("min", 20)):
                return "ADX below threshold"
            if cfg.get("rising", True) and (ann.get("adx_prev") is None or ann["adx"] <= ann["adx_prev"]):
                return "ADX not rising"
            if cfg.get("di", True) and not ann.get("di_ok"):
                return "DI against"
        if "acf" in g:
            if ann.get("acf1") is None or ann["acf1"] <= float(g["acf"].get("min", 0.0)):
                return "no persistence"
        if "require_gates" in g:
            for i in g["require_gates"]:
                if not read["gates"][i]:
                    return f"gate {eng.GATE_NAMES[i]} required"
        return None

    def _verdict_with_drop(self, read: dict) -> str:
        """Verdict recomputed without the dropped gates: of the remaining
        gates, 8/9 → exec, 7/9 → qualified (the 9/10 and 8/10 bars scaled)."""
        drop = set(self.rules["gates"].get("drop_gates", []))
        if not drop:
            return read["verdict"]
        if read["verdict"] == "BLOCKED" or read["mcc"] in ("DEAD_ZONE", "FAKE_BREAK"):
            return read["verdict"]
        kept = [v for i, v in enumerate(read["gates"]) if i not in drop]
        score = sum(1 for v in kept if v)
        k = len(kept)
        if score >= k - 1:
            return "EXEC_READY"
        if score >= k - 2:
            return "QUALIFIED"
        return "WAITING"

    def consider(self, m: core.Market, tf: str, window: list[dict], allow_open: bool = True,
                 trend_4h: Optional[str] = None, read: Optional[dict] = None):
        if self.rules["entry"] == "donchian":
            return self._consider_donchian(m, tf, window, allow_open, trend_4h)
        last = window[-1]
        if read is None:
            read = eng.evaluate(window, m.id, core.bar_close_hour(last, tf), self.news_week)
        else:
            read = dict(read)
        if not read:
            return read, None
        cfg = core.MODELS[self.model]
        mtf = cfg["mtf"] if self.rules["mtf"] is None else self.rules["mtf"]
        w5 = cfg["wave5_veto"] if self.rules["wave5_veto"] is None else self.rules["wave5_veto"]
        want = "up" if read["dir"] == "buy" else "down"
        read["trend_4h"] = trend_4h
        read["block"] = None
        if mtf and trend_4h != want:
            read["block"] = "4h trend " + ("flat" if trend_4h in (None, "flat") else "against")
        elif w5 and (read["elliott"]["label"] or "").startswith("Wave 5"):
            read["block"] = "Wave 5 exhaustion"
        if "drop_gates" in self.rules["gates"]:
            read["verdict"] = self._verdict_with_drop(read)
        if not allow_open or (m.id, tf) in self.open or read["block"]:
            return read, None
        if read["verdict"] not in ("EXEC_READY", "QUALIFIED") or not (read.get("sl_dist", 0) > 0):
            return read, None
        ann = self.annotate(m, tf, window, read)
        read["research"] = ann
        why = self.gates_pass(ann, read)
        if why:
            read["block"] = why
            return read, None
        t = self._open_from_read(m, tf, window, read, trend_4h)
        if t:
            self._post_open(t, m, window, ann)
        return read, t

    def _consider_donchian(self, m: core.Market, tf: str, window: list[dict], allow_open: bool,
                           trend_4h: Optional[str]):
        d = self.rules["donchian"]
        L = int(d.get("lookback", 20))
        if len(window) < L + 25:
            return None, None
        last = window[-1]
        prior = window[-L - 1:-1]
        hh, ll = max(b["high"] for b in prior), min(b["low"] for b in prior)
        direction = "buy" if last["close"] > hh else "sell" if last["close"] < ll else None
        read = {"dir": direction, "hh": hh, "ll": ll, "verdict": "EXEC_READY" if direction else "OBSERVER",
                "trend_4h": trend_4h, "block": None, "engine": "donchian-1", "entry": last["close"]}
        if not direction:
            return read, None
        if d.get("sides", "both") == "long" and direction == "sell":
            read["block"] = "longs only"
        elif d.get("sides", "both") == "short" and direction == "buy":
            read["block"] = "shorts only"
        elif d.get("trend", True) and trend_4h != ("up" if direction == "buy" else "down"):
            read["block"] = "4h trend " + ("flat" if trend_4h in (None, "flat") else "against")
        if not allow_open or (m.id, tf) in self.open or read["block"]:
            return read, None
        st = self.rules["stop"]
        p = int(st.get("period", 20)) if st.get("kind") == "atr" else 20
        mult = float(st.get("mult", 2.0)) if st.get("kind") == "atr" else 2.0
        a = wilder_atr(window[-(p * 3):], p)[-1]
        if not a or a <= 0:
            return read, None
        s = 1 if direction == "buy" else -1
        entry = last["close"]
        sl_dist = mult * a
        read.update({"sl_dist": sl_dist, "sl": entry - s * sl_dist, "atr": a})
        ann = self.annotate(m, tf, window, read)
        read["research"] = ann
        why = self.gates_pass(ann, read) if self.rules["gates"] else None
        if why:
            read["block"] = why
            return read, None
        cost = core.spread_for(m, entry) / sl_dist
        t = core.Trade(
            id=f"{m.id}-{tf}-{last['time']}", market=m.id, tf=tf, mode=m.mode, tier="exec", dir=direction,
            opened_at=last["time"] + core.TF_SEC[tf], entry=entry, sl=entry - s * sl_dist,
            tp1=entry + s * 1.5 * sl_dist, tp2=entry + s * 2.5 * sl_dist, sl_dist=sl_dist,
            cost_r=round(cost, 4), score=0, gates=[], mcc="", wyckoff="", pattern=None, rsi=None,
            last_bar=last["time"], engine="donchian-1", model=self.model, stop=entry - s * sl_dist,
            trend_4h=trend_4h, shadow={}, grade="other")
        self.open[(m.id, tf)] = t
        self._post_open(t, m, window, ann, atr=a)
        return read, t

    def _post_open(self, t: core.Trade, m: core.Market, window: list[dict], ann: dict,
                   atr: Optional[float] = None) -> None:
        st = self.rules["stop"]
        if self.rules["entry"] == "aria" and st.get("kind") == "atr":
            p = int(st.get("period", 20))
            a = wilder_atr(window[-(p * 3):], p)[-1]
            if a and a > 0:
                s = 1 if t.dir == "buy" else -1
                t.sl_dist = float(st.get("mult", 2.0)) * a
                t.sl = t.stop = t.entry - s * t.sl_dist
                t.tp1, t.tp2 = t.entry + s * 1.5 * t.sl_dist, t.entry + s * 2.5 * t.sl_dist
                t.cost_r = round(core.spread_for(m, t.entry) / t.sl_dist, 4)
                atr = a
        if atr is None and self.rules["exit"].get("kind") == "atr_trail":
            p = int(self.rules["exit"].get("period", 14))
            atr = wilder_atr(window[-(p * 3):], p)[-1]
        if not self.rules["shadows"]:
            t.shadow = {}
        t.model = self.model
        self.meta[t.id] = {"version": self.version, "atr": atr, "gates": ann}

    # — exits —
    def update(self, market: str, tf: str, bars: list[dict]) -> list[core.Trade]:
        kind = self.rules["exit"].get("kind", "model")
        t = self.open.get((market, tf))
        if not t:
            if kind == "channel":
                self._push_hist(market, tf, bars)      # the channel exit needs the bars before each new bar
            return []
        if kind == "model":
            return super().update(market, tf, bars)
        return self._update_research(t, tf, bars)

    def _update_research(self, t: core.Trade, tf: str, bars: list[dict]) -> list[core.Trade]:
        ex = self.rules["exit"]
        kind = ex["kind"]
        s = 1 if t.dir == "buy" else -1
        if t.stop is None:
            t.stop = t.sl
        meta = self.meta.get(t.id, {})
        atr = meta.get("atr") or t.sl_dist / 2.0
        k = float(ex.get("mult", 2.0))
        be = ex.get("breakeven_at")              # R at which the stop moves to entry (atr_trail only)
        timeout = int(ex.get("timeout", core.MODELS[self.model]["timeout"] or 96))
        N = int(ex.get("channel", 10))
        dq = self.hist.get((t.market, t.tf))
        for b in bars:
            if b["time"] <= t.last_bar:
                continue
            t.last_bar = b["time"]
            t.bars += 1
            lo_r = s * ((b["low"] if s > 0 else b["high"]) - t.entry) / t.sl_dist
            hi_r = s * ((b["high"] if s > 0 else b["low"]) - t.entry) / t.sl_dist
            t.mfe_r = max(t.mfe_r, hi_r)
            t.mae_r = max(t.mae_r, -lo_r)
            if hi_r >= 1.5:
                t.tp1_hit = True
            close_at = b["time"] + core.TF_SEC[tf]
            stop_r = s * (t.stop - t.entry) / t.sl_dist
            if lo_r <= stop_r:                                  # stop first, always
                self._close(t, "win" if stop_r > 0 else "loss", t.stop, stop_r, close_at)
                return [t]
            if kind == "fixed_r":
                tgt = float(ex.get("r", 2.0))
                if hi_r >= tgt:
                    self._close(t, "win", t.entry + s * tgt * t.sl_dist, tgt, close_at)
                    return [t]
            t.best_r = max(t.best_r, hi_r)
            if kind == "atr_trail":
                best_px = t.entry + s * t.best_r * t.sl_dist
                cand = best_px - s * k * atr
                if be is not None and t.best_r >= float(be):
                    cand = max(cand, t.entry) if s > 0 else min(cand, t.entry)
                if (s > 0 and cand > t.stop) or (s < 0 and cand < t.stop):
                    t.stop = cand
            elif kind == "channel" and dq is not None and len(dq) >= N:
                prior = list(dq)[-N:]
                lvl = min(x["low"] for x in prior) if s > 0 else max(x["high"] for x in prior)
                if (s > 0 and b["close"] < lvl) or (s < 0 and b["close"] > lvl):
                    gross = s * (b["close"] - t.entry) / t.sl_dist
                    self._close(t, "win" if gross > 0 else "loss", b["close"], gross, close_at)
                    return [t]
            if kind == "channel" and dq is not None:
                dq.append(b)
                self._hist_last[(t.market, t.tf)] = b["time"]
            locked = s * (t.stop - t.entry) / t.sl_dist
            if locked >= -1e-9:
                if t.protected_at is None:
                    t.protected_at = close_at
                t.locked_r = round(max(t.locked_r if t.locked_r is not None else locked, locked), 4)
            if t.bars >= timeout:
                gross = s * (b["close"] - t.entry) / t.sl_dist
                self._close(t, "timeout", b["close"], gross, close_at)
                return [t]
        return []

    def trade_record(self, t: core.Trade) -> dict:
        d = t.to_dict()
        d["_research"] = self.meta.get(t.id, {"version": self.version})
        return d


# ── History cache ────────────────────────────────────────────────────────────

def history_path(market: str, tf: str) -> str:
    return os.path.join(HISTORY_DIR, f"{market}_{tf}.json")


def load_history(markets: list[str], tfs: list[str]) -> dict[tuple[str, str], list[dict]]:
    data = {}
    for mid in markets:
        for tf in sorted(set(tfs) | {"4h"}, key=list(core.TF_SEC).index):
            p = history_path(mid, tf)
            if os.path.exists(p):
                data[(mid, tf)] = json.load(open(p))["bars"]
    return data


async def fetch_history(markets: list[str], pages: dict[str, int] = PAGES, pause: float = 20.0) -> None:
    os.makedirs(HISTORY_DIR, exist_ok=True)
    for mid in markets:
        m = core.MARKET_BY_ID[mid]
        for tf, pg in pages.items():
            p = history_path(mid, tf)
            if os.path.exists(p):
                continue
            bars = None
            for _ in range(4):
                try:
                    bars = await core.fetch_candles(m.deriv, tf, 5000, pages_back=pg)
                    break
                except Exception as e:                       # the public feed rate-limits per minute
                    print(f"retry {mid} {tf}: {e}", file=sys.stderr)
                    await asyncio.sleep(70)
            if not bars:
                continue
            json.dump({"market": mid, "deriv": m.deriv, "tf": tf, "fetched_at": int(time.time()), "bars": bars},
                      open(p, "w"))
            print(f"{mid} {tf} {len(bars)} bars", file=sys.stderr)
            await asyncio.sleep(pause)


# ── Replay ───────────────────────────────────────────────────────────────────

def reads_for(m: core.Market, tf: str, bars: list[dict], news_week: bool = False) -> list[Optional[dict]]:
    """ARIA's read of every bar (None before the warm-up). Depends only on the
    bars, so variants that differ in gates or exits share it."""
    W = core.WINDOW
    out: list[Optional[dict]] = [None] * len(bars)
    for i in range(W - 1, len(bars)):
        out[i] = eng.evaluate(bars[i - W + 1:i + 1], m.id, core.bar_close_hour(bars[i], tf), news_week)
    return out


def replay_slice(rules: dict, m: core.Market, tf: str, bars: list[dict], h4: Optional[list[dict]],
                 reads: Optional[list[Optional[dict]]] = None) -> list[dict]:
    """Exactly the live loop: score open trades on the new bar, then judge it."""
    book = ResearchBook(rules)
    ct, tr = core.trend_series(h4 or [])
    W = core.WINDOW
    for i in range(W - 1, len(bars)):
        book.update(m.id, tf, [bars[i]])
        if book.rules["shadows"]:
            book.update_shadows(m.id, tf, [bars[i]])
        t4 = core.trend_at(ct, tr, bars[i]["time"] + core.TF_SEC[tf]) if ct else None
        book.consider(m, tf, bars[i - W + 1:i + 1], trend_4h=t4, read=reads[i] if reads else None)
    return [book.trade_record(t) for t in book.closed]


def _job(args):
    """One worker: ARIA's reads for a slice once, then every variant over them.
    Variants with a Donchian entry ignore the reads."""
    variants, mid, tf, bars, h4 = args
    m = core.MARKET_BY_ID[mid]
    need_reads = any(normalize(r)["entry"] == "aria" for r in variants.values())
    reads = reads_for(m, tf, bars) if need_reads else None
    return (mid, tf), {name: replay_slice(r, m, tf, bars, h4, reads if normalize(r)["entry"] == "aria" else None)
                       for name, r in variants.items()}


def replay_many(variants: dict[str, dict], data: dict, slices: list[tuple[str, str]], workers: int = 2) -> dict[str, list[dict]]:
    jobs = [(variants, mid, tf, data[(mid, tf)], data.get((mid, "4h"))) for mid, tf in slices if (mid, tf) in data]
    if workers <= 1:
        results = [_job(j) for j in jobs]
    else:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            results = list(ex.map(_job, jobs))
    out: dict[str, list[dict]] = {name: [] for name in variants}
    for _, per in results:
        for name, ts in per.items():
            out[name].extend(ts)
    return out


def replay(rules: dict, data: dict, slices: list[tuple[str, str]], workers: int = 2) -> list[dict]:
    return replay_many({"x": rules}, data, slices, workers)["x"]


# ── Metrics ──────────────────────────────────────────────────────────────────

def _week(epoch: int) -> str:
    return time.strftime("%G-W%V", time.gmtime(epoch))


def _month(epoch: int) -> str:
    return time.strftime("%Y-%m", time.gmtime(epoch))


def wilson_lower(k: int, n: int, z: float = 1.96) -> Optional[float]:
    if n == 0:
        return None
    p = k / n
    den = 1 + z * z / n
    centre = p + z * z / (2 * n)
    adj = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (centre - adj) / den


def net_r(t: dict, cost_mult: float = 1.0) -> float:
    return (t["r"] or 0.0) - (t.get("cost_r") or 0.0) * (cost_mult - 1.0)


def metrics(trades: list[dict], cost_mult: float = 1.0, boot: int = 400, seed: int = 7) -> dict:
    done = [t for t in trades if t.get("status") in ("win", "loss", "timeout")]
    n = len(done)
    if not n:
        return {"n": 0}
    rs = [net_r(t, cost_mult) for t in done]
    gross = [(t["r"] or 0.0) + (t.get("cost_r") or 0.0) for t in done]
    exp = sum(rs) / n
    sd = (sum((r - exp) ** 2 for r in rs) / (n - 1)) ** 0.5 if n > 1 else 0.0
    se = sd / n ** 0.5 if n > 1 else float("inf")
    gains = sum(r for r in rs if r > 0)
    losses = -sum(r for r in rs if r < 0)
    eq = peak = dd = 0.0
    streak = worst_streak = 0
    for t, r in sorted(zip(done, rs), key=lambda x: x[0]["closed_at"] or 0):
        eq += r
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
        streak = streak + 1 if r < 0 else 0
        worst_streak = max(worst_streak, streak)
    # block bootstrap by ISO week: trades of one week move together
    weeks: dict[str, list[float]] = {}
    for t, r in zip(done, rs):
        weeks.setdefault(_week(t["opened_at"]), []).append(r)
    blocks = list(weeks.values())
    rng = random.Random(seed)
    means = []
    for _ in range(boot if len(blocks) > 2 else 0):
        pick = [rng.choice(blocks) for _ in blocks]
        flat = [x for blk in pick for x in blk]
        means.append(sum(flat) / len(flat))
    means.sort()
    ci_boot = [round(means[int(0.025 * len(means))], 4), round(means[int(0.975 * len(means)) - 1], 4)] if means else None
    months: dict[str, float] = {}
    for t, r in zip(done, rs):
        months[_month(t["opened_at"])] = months.get(_month(t["opened_at"]), 0.0) + r
    mvals = sorted(months.values(), reverse=True)
    total = sum(rs)
    thirds = []
    order = sorted(zip(done, rs), key=lambda x: x[0]["opened_at"])
    for k in range(3):
        part = order[k * n // 3:(k + 1) * n // 3]
        thirds.append(round(sum(r for _, r in part), 2) if part else 0.0)
    wins = sum(1 for t in done if t["status"] == "win")
    best = max(rs)
    reg: dict[str, int] = {}
    for t in done:
        reg[t.get("trend_4h") or "none"] = reg.get(t.get("trend_4h") or "none", 0) + 1
    cost = sum((t.get("cost_r") or 0.0) * cost_mult for t in done) / n
    agross = sum(abs(g) for g in gross) / n
    return {
        "n": n, "wins": wins, "win_rate": round(wins / n, 4), "wilson_lower_win": round(wilson_lower(wins, n), 4),
        "expectancy_r": round(exp, 4), "gross_expectancy_r": round(sum(gross) / n - 0.0, 4),
        "ci95_r": [round(exp - 1.96 * se, 4), round(exp + 1.96 * se, 4)] if n > 1 else None,
        "ci95_block_r": ci_boot, "se_r": round(se, 5) if n > 1 else None,
        "total_r": round(total, 2), "profit_factor": round(gains / losses, 3) if losses else None,
        "max_drawdown_r": round(dd, 2), "longest_losing_streak": worst_streak,
        "timeouts": sum(1 for t in done if t["status"] == "timeout"),
        "avg_cost_r": round(cost, 4), "cost_share": round(cost / agross, 3) if agross else None,
        "months": len(months), "months_positive_share": round(sum(1 for v in months.values() if v > 0) / len(months), 3),
        "best_two_months_share": round(sum(mvals[:2]) / total, 3) if total > 0 and mvals else None,
        "thirds_r": thirds, "thirds_positive": sum(1 for x in thirds if x > 0),
        "best_trade_removed_r": round((total - best) / (n - 1), 4) if n > 1 else None,
        "regimes": reg, "cost_mult": cost_mult,
        "mfe_avg_r": round(sum(t.get("mfe_r") or 0 for t in done) / n, 3),
        "never_reached_half_r": round(sum(1 for t in done if (t.get("mfe_r") or 0) < 0.5) / n, 3),
    }


def by_slice(trades: list[dict], cost_mult: float = 1.0) -> dict[str, dict]:
    groups: dict[str, list[dict]] = {}
    for t in trades:
        groups.setdefault(f"{t['market']} {t['tf']}", []).append(t)
    return {k: metrics(v, cost_mult, boot=0) for k, v in sorted(groups.items())}


# ── Splits and tests ─────────────────────────────────────────────────────────

def split_bounds(data: dict, dev: float = 0.5, val: float = 0.2) -> dict:
    t0 = min(b[0]["time"] for b in data.values() if b)
    t1 = max(b[-1]["time"] for b in data.values() if b)
    return {"start": t0, "dev_end": int(t0 + dev * (t1 - t0)), "val_end": int(t0 + (dev + val) * (t1 - t0)), "end": t1}


def window_of(t: dict, b: dict) -> str:
    o = t["opened_at"]
    return "dev" if o < b["dev_end"] else "val" if o < b["val_end"] else "holdout"


def split(trades: list[dict], b: dict) -> dict[str, list[dict]]:
    out = {"dev": [], "val": [], "holdout": []}
    for t in trades:
        out[window_of(t, b)].append(t)
    return out


def placebo_test(base: list[dict], accepted: list[bool], n_perm: int = 1000, seed: int = 11) -> dict:
    """#3977's test: is the accepted subset better than random subsets of the
    same size drawn from the same base trades? Reported for net and gross R.
    p = share of random subsets whose mean is >= the accepted mean."""
    done = [(t, a) for t, a in zip(base, accepted) if t.get("status") in ("win", "loss", "timeout")]
    acc = [t for t, a in done if a]
    k, n = len(acc), len(done)
    if k == 0 or k == n or n < 20:
        return {"n_base": n, "n_accepted": k, "p_net": None, "p_gross": None}
    net = [net_r(t) for t, _ in done]
    grs = [(t["r"] or 0.0) + (t.get("cost_r") or 0.0) for t, _ in done]
    acc_net = sum(net_r(t) for t in acc) / k
    acc_gross = sum((t["r"] or 0.0) + (t.get("cost_r") or 0.0) for t in acc) / k
    rng = random.Random(seed)
    idx = list(range(n))
    ge_net = ge_gross = 0
    for _ in range(n_perm):
        pick = rng.sample(idx, k)
        if sum(net[i] for i in pick) / k >= acc_net:
            ge_net += 1
        if sum(grs[i] for i in pick) / k >= acc_gross:
            ge_gross += 1
    return {"n_base": n, "n_accepted": k, "accepted_net_r": round(acc_net, 4), "base_net_r": round(sum(net) / n, 4),
            "accepted_gross_r": round(acc_gross, 4), "base_gross_r": round(sum(grs) / n, 4),
            "p_net": round(ge_net / n_perm, 4), "p_gross": round(ge_gross / n_perm, 4), "permutations": n_perm}


def gate_mask(base_trades: list[dict], gate: str, cfg: Any) -> list[bool]:
    """Would this gate have accepted each base trade? Read from the gate
    annotations the base run recorded at signal time (no slot effect)."""
    out = []
    for t in base_trades:
        g = (t.get("_research") or {}).get("gates") or {}
        if gate == "session":
            out.append(session_ok(cfg, t["market"], t["opened_at"]))
        elif gate == "cost_cap":
            out.append(g.get("cost_r") is not None and g["cost_r"] <= float(cfg))
        elif gate == "adx":
            ok = g.get("adx") is not None and g["adx"] >= float(cfg.get("min", 20))
            if cfg.get("rising", True):
                ok = ok and g.get("adx_prev") is not None and g["adx"] > g["adx_prev"]
            if cfg.get("di", True):
                ok = ok and bool(g.get("di_ok"))
            out.append(ok)
        elif gate == "acf":
            out.append(g.get("acf1") is not None and g["acf1"] > float(cfg.get("min", 0.0)))
        else:
            raise ValueError(gate)
    return out


# ── Experiments ──────────────────────────────────────────────────────────────

def experiment(spec: dict, data: dict, workers: int = 2, log=print) -> dict:
    """
    spec = {"id", "hypothesis", "slices": [[market, tf], ...], "base": rules,
            "variants": {name: rules}, "filter_tests": [{"variant": name, "gate": g, "cfg": ...}],
            "neighbourhood": {"gate": g, "cells": [{"label":..., "cfg":...}, ...]}}
    Every variant is replayed in full (slot effects included). Filter tests
    and the neighbourhood table use the base run's gate readings for the
    placebo comparison (no slot effect, #3977).
    """
    t0 = time.time()
    slices = [tuple(s) for s in spec["slices"]]
    bounds = split_bounds({k: v for k, v in data.items() if k in slices})
    base_rules = normalize(spec.get("base") or {})
    # the base run records ADX/ACF readings for every signal without filtering on them
    readings = {}
    for v in list(spec.get("variants", {}).values()) + [{"gates": {ft["gate"]: ft["cfg"]}} for ft in spec.get("filter_tests", [])]:
        for g, cfg in (v.get("gates") or {}).items():
            if g in ("adx", "acf"):
                readings.setdefault(g, {**cfg, "readings_only": True})
    nb = spec.get("neighbourhood")
    if nb and nb["gate"] in ("adx", "acf"):
        for cell in nb["cells"]:
            readings.setdefault(nb["gate"], {**cell["cfg"], "readings_only": True})
    base_ann = dict(base_rules)
    base_ann["gates"] = {**base_rules["gates"], **readings}
    variants = {"base": base_ann, **spec.get("variants", {})}
    runs = replay_many(variants, data, slices, workers)
    base_trades = runs["base"]
    log(f"  replayed {len(variants)} rule sets over {len(slices)} slices in {time.time()-t0:.0f}s; base {len(base_trades)} trades")
    out: dict[str, Any] = {"id": spec["id"], "hypothesis": spec.get("hypothesis"), "generated": int(time.time()),
                           "bounds": bounds, "slices": [list(s) for s in slices], "base_rules": base_rules,
                           "base_version": rules_id(spec.get("base") or {}), "variants": {}, "filter_tests": {},
                           "neighbourhood": [], "configurations_tried": 0}
    for name, ts in runs.items():
        out["variants"][name] = _summ(ts, bounds)
        out["variants"][name]["rules"] = normalize(variants[name])
        out["variants"][name]["version"] = rules_id(variants[name]) if name != "base" else out["base_version"]
        if name != "base":
            out["configurations_tried"] += 1
        d, v = out["variants"][name]["dev"]["x1.0"], out["variants"][name]["val"]["x1.0"]
        log(f"  {name:14s} n {len(ts):5d}  dev {d.get('expectancy_r')} (n {d.get('n')})  val {v.get('expectancy_r')} (n {v.get('n')})")
    sp = split(base_trades, bounds)
    for ft in spec.get("filter_tests", []):
        res = {}
        for w in ("dev", "val", "holdout"):
            mask = gate_mask(sp[w], ft["gate"], ft["cfg"])
            res[w] = placebo_test(sp[w], mask)
        out["filter_tests"][ft["variant"]] = {"gate": ft["gate"], "cfg": ft["cfg"], **res}
    if nb:
        for cell in nb["cells"]:
            row = {"label": cell["label"], "cfg": cell["cfg"]}
            for w in ("dev", "val", "holdout"):
                mask = gate_mask(sp[w], nb["gate"], cell["cfg"])
                acc = [t for t, a in zip(sp[w], mask) if a]
                m = metrics(acc, boot=0)
                row[w] = {"n": m.get("n", 0), "expectancy_r": m.get("expectancy_r"), "gross": m.get("gross_expectancy_r")}
            out["neighbourhood"].append(row)
            out["configurations_tried"] += 1
    out["seconds"] = round(time.time() - t0)
    return out


def _summ(trades: list[dict], bounds: dict) -> dict:
    sp = split(trades, bounds)
    out: dict[str, Any] = {"n": len(trades)}
    for w, ts in sp.items():
        out[w] = {f"x{c}": metrics(ts, c) for c in (1.0, 1.5, 2.0)}
        out[w]["by_slice"] = by_slice(ts)
    out["all"] = {f"x{c}": metrics(trades, c) for c in (1.0, 1.5, 2.0)}
    out["all"]["by_slice"] = by_slice(trades)
    return out



# ── Reporting ────────────────────────────────────────────────────────────────

def _fmt(m: dict) -> str:
    if not m or not m.get("n"):
        return "n 0"
    ci = m.get("ci95_r") or [float("nan")] * 2
    return (f"n {m['n']:5d}  exp {m['expectancy_r']:+.3f}R [{ci[0]:+.3f},{ci[1]:+.3f}]  gross {m.get('gross_expectancy_r', 0):+.3f}  "
            f"PF {m.get('profit_factor') or 0:.2f}  DD {m.get('max_drawdown_r', 0):.1f}R  cost {m.get('avg_cost_r', 0):.3f}")


def report(res: dict) -> str:
    """Readable summary of an experiment() result: windows x costs per variant,
    placebo tests, neighbourhood table. Development numbers are development
    evidence; nothing here is forward evidence."""
    b = res["bounds"]
    d = lambda e: time.strftime("%Y-%m-%d", time.gmtime(e))
    out = [f"# Experiment {res['id']} (hypothesis {res.get('hypothesis')}) — generated {d(res['generated'])}",
           f"windows: development {d(b['start'])} → {d(b['dev_end'])} · validation → {d(b['val_end'])} · holdout → {d(b['end'])} "
           f"(holdout reused across hypotheses; logged)",
           f"configurations tried: {res['configurations_tried']} · slices: {len(res['slices'])} · base version {res['base_version']}", ""]
    for name, v in res["variants"].items():
        out.append(f"## {name}  (version {v.get('version')}, n {v['n']})")
        for w in ("dev", "val", "holdout", "all"):
            for c in ("x1.0", "x1.5", "x2.0"):
                m = v[w][c]
                tag = f"{w:8s} {c}"
                out.append(f"  {tag:14s} {_fmt(m)}" + (f"  thirds {m.get('thirds_r')}" if c == "x1.0" and m.get("n") else ""))
        sl = v["val"]["by_slice"]
        if sl:
            out.append("  validation by slice: " + "; ".join(f"{k} {m['expectancy_r']:+.2f} (n {m['n']})" for k, m in sl.items() if m.get("n")))
        out.append("")
    if res.get("filter_tests"):
        out.append("## Placebo tests (accepted subset vs 1,000 random subsets of equal size, from the base run's signals)")
        for name, ft in res["filter_tests"].items():
            out.append(f"  {name} ({ft['gate']}):")
            for w in ("dev", "val", "holdout"):
                r = ft[w]
                if r.get("p_net") is None:
                    out.append(f"    {w:8s} not testable (n_base {r.get('n_base')}, accepted {r.get('n_accepted')})")
                else:
                    out.append(f"    {w:8s} accepted {r['n_accepted']}/{r['n_base']}  net {r['accepted_net_r']:+.3f} vs base {r['base_net_r']:+.3f} (p {r['p_net']:.3f})  "
                               f"gross {r['accepted_gross_r']:+.3f} vs {r['base_gross_r']:+.3f} (p {r['p_gross']:.3f})")
        out.append("")
    if res.get("neighbourhood"):
        out.append("## Parameter neighbourhood (accepted subset of base signals; look for a plateau, not a peak)")
        out.append(f"  {'cell':24s} {'dev n':>6s} {'dev exp':>8s} {'val n':>6s} {'val exp':>8s} {'hold n':>6s} {'hold exp':>8s}")
        for row in res["neighbourhood"]:
            f = lambda w: (f"{row[w]['n']:6d} {row[w]['expectancy_r'] if row[w]['expectancy_r'] is not None else float('nan'):+8.3f}")
            out.append(f"  {row['label']:24s} {f('dev')} {f('val')} {f('holdout')}")
    return "\n".join(out)


# ── CLI ──────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["fetch", "run", "baseline", "report"])
    ap.add_argument("name", nargs="?")
    ap.add_argument("--workers", type=int, default=2)
    a = ap.parse_args()
    if a.cmd == "fetch":
        asyncio.run(fetch_history(FOCUS))
        return
    if a.cmd == "report":
        print(report(json.load(open(os.path.join(EXPERIMENTS_DIR, f"{a.name}.result.json")))))
        return
    data = load_history(FOCUS, ["15m", "1h", "4h"])
    if a.cmd == "baseline":
        slices = [(m, tf) for m in FOCUS for tf in ("15m", "1h")]
        ts = replay({}, data, slices, a.workers)
        b = split_bounds(data)
        print(json.dumps({"n": len(ts), "all": metrics(ts), "by_slice": by_slice(ts), "bounds": b}, indent=1))
        return
    spec = json.load(open(os.path.join(EXPERIMENTS_DIR, f"{a.name}.json")))
    res = experiment(spec, data, a.workers)
    os.makedirs(EXPERIMENTS_DIR, exist_ok=True)
    outp = os.path.join(EXPERIMENTS_DIR, f"{a.name}.result.json")
    json.dump(res, open(outp, "w"), indent=1)
    print(f"wrote {outp} in {res['seconds']}s")


if __name__ == "__main__":
    main()
