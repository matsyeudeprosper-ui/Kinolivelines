"""owl_scanner.py - the setup scanner (owner 2026-10-11).

"Make the market page a place where the app scans other symbols and shows
which have a setup ready. First version: virtual trades only, keep records,
and see whether the backtests of the new symbols match the forward test."

v2 (owner, same day): the scanner must play the ROBOT's setup, not a cousin
of it. So the signals now come from the robot's own code:

  * structure_bos_bot.Struct - the robot's incremental structure engine,
    seeded with SEED_BARS (3000) closed M1 bars and then stepped on every
    closed bar, exactly like the bot's main loop;
  * an entry is the bar the engine returns a signal on: entry at the CLOSE
    beyond the BOS level (ask for a buy), stop = the new protected dot the
    engine returns, target 0.8 x the risk (the robot's RR);
  * pb_gate.pb_gate("trend", ...) - the SAME function the live bot calls -
    with the pullback chart's state from the last 8000 closed bars (the
    feed's build/engine/pullback_view, prices scaled so the engine's 2-dp
    rounding keeps a currency's precision). The live bot also reads a sticky
    chain of past pullback candles; the scanner cannot have one for every
    symbol in the past, so backtest and forward both read the plain view;
  * the robot's minimum stop: 10 pts on BTC (S_MIN_DIST, the spread zone);
    on other symbols the same idea scaled to their spread (10/7 x spread).
  * one virtual position per symbol at a time (the bot's my_positions()).

  NOT modelled (said on the page): the weather brakes, the debt/recovery
  rules, lot sizing, the internal structure, day caps. Results are in R.

Read only: this file never sends an order. It attaches to the chart feed's
demo terminal without logging in.

Files (live/scanner/): state.json, forward.jsonl, backtest_<SYM>.json, scanner.log

    python owl_scanner.py                 # the daemon
    python owl_scanner.py --once          # one pass, print the states
    python owl_scanner.py --backtest XAUUSD --days 30
    python owl_scanner.py --backtest all --days 30
"""
import importlib.util
import json
import os
import sys
import time
from datetime import datetime, timezone

import MetaTrader5 as mt5

DIR = os.path.dirname(os.path.abspath(__file__))
OUTD = os.path.join(DIR, "scanner")
# 2026-10-11 (GPT review of 59f09ee): the engine is loaded ONLY from the isolated, immutable bundle
# (live/scanner/build_engine_bundle.py). The working tree is taken off the import path so a product edit to
# the robot or the chart can never change the scanner's signals; every loaded module is checked (isolation()).
BUNDLE = os.path.join(OUTD, "engine_f2")
MANIFEST = os.path.join(BUNDLE, "BUNDLE_MANIFEST.json")
sys.path[:] = [p for p in sys.path if os.path.normcase(os.path.abspath(p or ".")) != os.path.normcase(DIR)]
sys.path.insert(0, BUNDLE)
os.makedirs(OUTD, exist_ok=True)
STATE = os.path.join(OUTD, "state.json")
LOGF = os.path.join(OUTD, "scanner.log")
TERMINAL = r"C:\NestTerminals\u476954287\terminal64.exe"
ENGINE = "v2-robot-struct"

SYMBOLS = [
    # 2026-10-11 (owner: "not the same move as BTC"): ETHUSD dropped - its hourly
    # returns correlate 0.85 with BTC over 60 days; every symbol kept is under 0.35.
    ("BTCUSD", "Bitcoin", "crypto"),
    ("XAUUSD", "Or", "metal"), ("XAGUSD", "Argent", "metal"),
    ("USOIL", "Pétrole US", "energy"),
    ("US30", "Dow Jones", "index"), ("USTEC", "Nasdaq 100", "index"), ("US500", "S&P 500", "index"),
    ("DE30", "DAX", "index"), ("UK100", "FTSE 100", "index"), ("JP225", "Nikkei 225", "index"),
    ("EURUSD", "Euro / Dollar", "fx"), ("GBPUSD", "Livre / Dollar", "fx"), ("USDJPY", "Dollar / Yen", "fx"),
]
MAX_CORR = 0.5
LATE_S = 90             # a signal whose candle closed more than this many seconds ago is not tradeable
PB_BARS = 8000          # the pullback state's window (structure_bos_bot.pb_state_now)
FETCH = PB_BARS + 300   # bars read per minute in the daemon
BTC_SPREAD_REF = 7.0    # BTC's spread on this broker, in points - S_MIN_DIST is 10 at that spread


def log(m):
    try:
        with open(LOGF, "a", encoding="utf-8") as f:
            f.write(datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ ") + m + "\n")
    except Exception:
        pass


_F = None
_B = None


def feed():
    global _F
    if _F is None:
        p = os.path.join(BUNDLE, "owl_chart_feed.py")
        sp = importlib.util.spec_from_file_location("owl_chart_feed_scan", p)
        m = importlib.util.module_from_spec(sp)
        sp.loader.exec_module(m)
        _F = m
    return _F


def bot():
    """the live robot's module, for Struct / RR / SEED_BARS / S_MIN_DIST (its
    main() is not run; argv is masked so it picks no account variant)"""
    global _B
    if _B is None:
        saved = sys.argv
        sys.argv = ["owl_scanner"]
        try:
            import structure_bos_bot as B
        finally:
            sys.argv = saved
        B.say = lambda *a, **k: None
        _B = B
    return _B


def scale_of(digits):
    return 10 ** max(0, int(digits) - 2)


def rows_of(R, digits):
    s = scale_of(digits)
    return [{"time": int(r["time"]), "open": float(r["open"]) * s, "high": float(r["high"]) * s,
             "low": float(r["low"]) * s, "close": float(r["close"]) * s} for r in R]


def pb_state(rows, k, digits):
    """(trend, pending CHoCH dir, CHoCH price, last BOS price) of the pullback chart
    from rows[k-7999 .. k] - structure_bos_bot.pb_state_now()'s arithmetic, no sticky chain"""
    F = feed()
    s = scale_of(digits)
    g0 = max(0, k - PB_BARS + 1)
    try:
        kept = F.build(rows[g0:k + 1])
        if len(kept) < 3:
            return (0, 0, None, None)
        bk = []
        d, m, tr, *_ = F.engine(kept, brk_out=bk)
        if tr:
            d = [x for x in d if x[2] == tr]
        pb = F.pullback_view(kept, d, m, bk, write=False) or {}
        t_ = int(pb.get("trend") or 0); c_ = int(pb.get("choch") or 0)
        c_ = c_ if (c_ and c_ != t_) else 0
        lvl = None
        if c_:
            cm = [x for x in (pb.get("marks") or []) if len(x) > 2 and x[2] == "choch"]
            lvl = float(cm[-1][1]) / s if cm else None
        bks = pb.get("breaks") or []
        return (t_, c_, lvl, float(bks[-1][2]) / s if bks else None)
    except Exception:
        return (0, 0, None, None)


def spread_px(r, point):
    try:
        return float(r["spread"]) * point
    except Exception:
        return 0.0


def min_dist(sym, sp):
    B = bot()
    return float(B.S_MIN_DIST) if sym == "BTCUSD" else float(B.S_MIN_DIST) / BTC_SPREAD_REF * sp


class Sym:
    """one symbol's robot engine, stepped like the bot's main loop"""

    def __init__(self, sym):
        self.sym = sym
        self.eng = bot().Struct()
        self.eng.quiet = True
        self.last = 0

    def seed(self, R):
        for r in R:
            self.eng.step(int(r["time"]), float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]))
            self.last = int(r["time"])
        self.eng.quiet = True

    def step(self, r):
        pt = self.eng.trend
        sig = self.eng.step(int(r["time"]), float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]))
        self.last = int(r["time"])
        if not sig:
            return None
        return {"d": int(sig[0]), "sl": float(sig[1]), "flip": self.eng.trend != pt}


def try_entry(sym, info, R, k, sig, rows):
    """the bot's enter() checks that apply here: pb_gate('trend'), the minimum stop"""
    from pb_gate import pb_gate
    r = R[k]
    sp = spread_px(r, info.point)
    d, sl = sig["d"], sig["sl"]
    px = float(r["close"]) + (sp if d == 1 else 0.0)     # bars are BID: ask = bid + spread
    st = pb_state(rows, k, info.digits)
    ok, why = pb_gate("trend", d, px, *st)
    if not ok:
        return None, why
    dist = abs(px - sl)
    if d * (px - sl) <= 0:
        return None, "stop_wrong_side"
    if dist <= min_dist(sym, sp):
        return None, "stop_in_spread_zone"
    RR = float(bot().RR)
    return {"sym": sym, "d": d, "t": int(r["time"]), "e": px, "sl": sl, "tp": px + d * RR * dist, "risk": dist,
            "spread": sp, "flip": sig["flip"], "pb": st[0], "pb_bos": st[3], "engine": ENGINE}, None


def step_trade(tr, r, point):
    sp = spread_px(r, point)
    hi, lo = float(r["high"]), float(r["low"])
    if tr["d"] == 1:
        hit_sl, hit_tp = lo <= tr["sl"], hi >= tr["tp"]
    else:
        hit_sl, hit_tp = hi + sp >= tr["sl"], lo + sp <= tr["tp"]
    if not (hit_sl or hit_tp):
        return None
    win = hit_tp and not hit_sl
    x = tr["tp"] if win else tr["sl"]
    c = dict(tr)
    c.update({"x": x, "xt": int(r["time"]), "win": win, "r": round(tr["d"] * (x - tr["e"]) / tr["risk"], 3),
              "both": bool(hit_sl and hit_tp)})
    return c


def summary(trs):
    n = len(trs)
    if not n:
        return {"n": 0}
    rs = [t["r"] for t in trs]
    w = [x for x in rs if x > 0]
    gl = -sum(x for x in rs if x <= 0)
    return {"n": n, "wins": len(w), "wr": round(100 * len(w) / n, 1), "sum_r": round(sum(rs), 2),
            "avg_r": round(sum(rs) / n, 3), "pf": round(sum(w) / gl, 2) if gl > 0 else None}


# ---------------------------------------------------------------- backtest
def backtest(sym, days, end_ago=0.0, save=True):
    info = mt5.symbol_info(sym)
    if info is None:
        return {"sym": sym, "err": "symbol not found"}
    mt5.symbol_select(sym, True)
    seed = int(bot().SEED_BARS)
    # 2026-10-11 (GPT review): the window is CALENDAR days, the same span for every
    # market. Bars are read until PB_BARS of history sit before the window's start.
    end = time.time() - end_ago * 86400
    start = end - days * 86400
    n = PB_BARS + int((days + end_ago) * 1440) + 10
    R = None
    for _ in range(6):
        R = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 1, n)
        if R is None or len(R) < 100:
            break
        k0 = next((i for i in range(len(R)) if int(R[i]["time"]) >= start), len(R))
        if k0 >= PB_BARS or len(R) < n:
            break
        n = int(n * 1.6)
    if R is None or len(R) < PB_BARS + 100:
        return {"sym": sym, "err": "not enough history (%s bars)" % (0 if R is None else len(R))}
    k0 = next((i for i in range(len(R)) if int(R[i]["time"]) >= start), len(R))
    if k0 < PB_BARS:
        return {"sym": sym, "err": "not enough history before the window (%d bars)" % k0}
    t0 = time.time()
    rows = rows_of(R, info.digits)
    S = Sym(sym)
    S.seed(R[k0 - seed:k0])          # the bot seeds with SEED_BARS closed bars
    trades, refused, open_tr, sigs = [], {}, None, 0
    k1 = next((i for i in range(len(R)) if int(R[i]["time"]) >= end), len(R))
    for k in range(k0, k1):
        r = R[k]
        if open_tr is not None:
            done = step_trade(open_tr, r, info.point)
            if done:
                trades.append(done)
                open_tr = None
        sig = S.step(r)
        if sig:
            sigs += 1
            if open_tr is not None:
                refused["position_open"] = refused.get("position_open", 0) + 1
                continue
            tr, why = try_entry(sym, info, R, k, sig, rows)
            if tr:
                open_tr = tr
            else:
                refused[why] = refused.get(why, 0) + 1
    if open_tr is not None:
        # GPT review: one explicit end-of-window rule for strategy AND controls - a position still open at
        # the window's end is closed at the last window bar's close (bid for a buy, ask for a sell), flagged
        rl = R[k1 - 1]
        xp = float(rl["close"]) + (0.0 if open_tr["d"] == 1 else spread_px(rl, info.point))
        c = dict(open_tr)
        c.update({"x": xp, "xt": int(rl["time"]), "win": open_tr["d"] * (xp - open_tr["e"]) > 0,
                  "r": round(open_tr["d"] * (xp - open_tr["e"]) / open_tr["risk"], 3), "eow": True})
        trades.append(c)
    out = {"sym": sym, "days": days, "calendar": True, "bars": len(R) - k0, "engine": ENGINE,
           "from": int(R[k0]["time"]), "to": int(R[k1 - 1]["time"]), "end_ago": end_ago,
           "built": int(time.time()), "secs": round(time.time() - t0, 1), "signals": sigs, "refused": refused,
           "summary": summary(trades), "trades": trades[-500:]}
    out["_R"] = (R, k0, k1, info.point)          # for callers that need the bars (not saved)
    if save:
        json.dump({k: v for k, v in out.items() if k != "_R"}, open(os.path.join(OUTD, "backtest_%s.json" % sym), "w", encoding="utf-8"))
    return out


# ------------------------------------------------------------------ forward
# ------------------------------------------------------------------ forward (v3: quotes)
# 2026-10-11 (GPT review of b8aea4d): v2 found a signal up to a minute after the
# candle closed but booked the entry at that candle's close, and judged exits on
# whole M1 bars that began before the entry. v3:
#   * the daemon polls every POLL_S seconds for a newly closed candle;
#   * an entry is booked at a FRESH quote read at detection (ask for a buy, bid
#     for a sell), with the detection latency and the quote's age recorded;
#   * no quote, or one older than QUOTE_MAX_AGE, = the signal is MISSED (logged);
#   * a quote already beyond the stop = MISSED ("price_through_stop");
#   * exits are judged on TICKS strictly after the entry tick: a buy's stop at the
#     first bid <= SL, filled at that bid (a gap below the stop is recorded as
#     slippage); its target at the first bid >= TP, filled at TP (limit). Mirror
#     for a sell on the ask. Ticks with a zero bid/ask are skipped and counted.
#   * after a restart an open trade is replayed on ticks from its entry.
# v2 records (close-price model) stay in forward_v2_close.jsonl, never mixed.
ENGINE_FWD = "v3-quote"
FWD = os.path.join(OUTD, "forward_v3.jsonl")
FWD_V2 = os.path.join(OUTD, "forward_v2_close.jsonl")
POLL_S = 5
QUOTE_MAX_AGE = 30.0
# 2026-10-11 (GPT review of 59f09ee): the guard FAILS CLOSED. No new virtual trade unless the bundle manifest
# exists, parses, lists every required file, every hash matches, the runner's hash matches, and every engine
# module in memory was loaded from the bundle. Checked at startup before the first entry, then every minute.
HB = os.path.join(OUTD, "heartbeat.jsonl")
ENGINE_MODS = ("structure_bos_bot", "owl_package", "owl_shadow", "pb_gate")


def _sha(p):
    import hashlib
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def isolation():
    """engine modules loaded from outside the bundle (empty list = isolated)"""
    bad = []
    root = os.path.normcase(os.path.abspath(BUNDLE))
    for m in ENGINE_MODS:
        mod = sys.modules.get(m)
        if mod is None or not os.path.normcase(os.path.abspath(getattr(mod, "__file__", "") or "")).startswith(root):
            bad.append("isolation:" + m)
    if _F is None or not os.path.normcase(os.path.abspath(_F.__file__)).startswith(root):
        bad.append("isolation:owl_chart_feed")
    return bad


def drift():
    """None when everything checks, else the list of problems (fail closed)"""
    try:
        man = json.load(open(MANIFEST, encoding="utf-8"))
        files, req, run = man["files"], man["required"], man["runner"]
    except Exception:
        return ["manifest_missing_or_invalid"]
    bad = ["incomplete:" + f for f in req if f not in files]
    for f, h in files.items():
        p = os.path.join(BUNDLE, f)
        if not os.path.exists(p):
            bad.append("missing:" + f)
        elif _sha(p) != h:
            bad.append("changed:" + f)
    if run.get("owl_scanner.py") != _sha(os.path.abspath(__file__)):
        bad.append("changed:owl_scanner.py")
    bad += isolation()
    return bad or None


def load_open():
    op = {}
    try:
        for ln in open(FWD, encoding="utf-8"):
            x = json.loads(ln)
            if x.get("engine") != ENGINE_FWD:
                continue
            if x.get("ev") == "open":
                op[x["sym"]] = x
            elif x.get("ev") == "close":
                op.pop(x["sym"], None)
    except Exception:
        pass
    return op


def append(rec):
    rec.setdefault("engine", ENGINE_FWD)
    with open(FWD, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


_CORR = {"t": 0, "v": {}}


def btc_corr():
    if time.time() - _CORR["t"] < 6 * 3600 and _CORR["v"]:
        return _CORR["v"]
    import numpy as np
    H = {}
    for sym, _n, _c in SYMBOLS:
        R = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, 24 * 60)
        if R is not None:
            H[sym] = {int(r["time"]): float(r["close"]) for r in R}
    out = {}
    b = H.get("BTCUSD") or {}
    for sym in H:
        if sym == "BTCUSD":
            continue
        ts = sorted(set(b) & set(H[sym]))
        if len(ts) < 100:
            continue
        x = np.diff(np.log([b[t] for t in ts])); y = np.diff(np.log([H[sym][t] for t in ts]))
        g = np.diff(ts) == 3600
        if g.sum() > 50:
            out[sym] = round(float(np.corrcoef(x[g], y[g])[0, 1]), 2)
    _CORR["t"], _CORR["v"] = time.time(), out
    return out


def quote_entry(sym, info, R, j, sig, rows):
    """the entry at a fresh quote, or (None, reason)"""
    from pb_gate import pb_gate
    now = time.time()
    bar_close = int(R[j]["time"]) + 60
    lat = now - bar_close
    if lat > LATE_S:
        return None, "late", {"latency_s": round(lat, 1)}
    tk = mt5.symbol_info_tick(sym)
    if tk is None or not tk.bid or not tk.ask:
        return None, "no_quote", {"latency_s": round(lat, 1)}
    qt = tk.time_msc / 1000.0
    age = now - qt
    if age > QUOTE_MAX_AGE:
        return None, "stale_quote", {"latency_s": round(lat, 1), "quote_age_s": round(age, 1)}
    d, sl = sig["d"], sig["sl"]
    px = float(tk.ask) if d == 1 else float(tk.bid)
    sp = float(tk.ask) - float(tk.bid)
    st = pb_state(rows, j, info.digits)
    ok, why = pb_gate("trend", d, px, *st)
    meta = {"latency_s": round(lat, 1), "quote_age_s": round(age, 1), "spread": sp}
    if not ok:
        return None, why, meta
    if d * (px - sl) <= 0:
        return None, "price_through_stop", meta
    dist = abs(px - sl)
    if dist <= min_dist(sym, sp):
        return None, "stop_in_spread_zone", meta
    RR = float(bot().RR)
    tr = {"sym": sym, "d": d, "sig_bar": int(R[j]["time"]), "bar_close_px": float(R[j]["close"]),
          "t": int(qt), "t_msc": int(tk.time_msc), "detect": round(now, 3), "e": px, "sl": sl,
          "tp": px + d * RR * dist, "risk": dist, "flip": sig["flip"], "pb": st[0], "pb_bos": st[3],
          "chk_msc": int(tk.time_msc)}
    tr.update(meta)
    return tr, None, meta


def tick_exit(tr, sym, upto=None):
    """walk the ticks after tr['chk_msc']; returns the closed trade or None (updates chk_msc)"""
    t_from = datetime.fromtimestamp(tr["chk_msc"] / 1000.0 + 0.001, tz=timezone.utc)
    t_to = datetime.fromtimestamp(upto or time.time(), tz=timezone.utc)
    T = mt5.copy_ticks_range(sym, t_from, t_to, mt5.COPY_TICKS_ALL)
    if T is None or len(T) == 0:
        return None
    bad = 0
    d, sl, tp = tr["d"], tr["sl"], tr["tp"]
    for x in T:
        ms = int(x["time_msc"])
        if ms <= tr["chk_msc"]:
            continue
        b, a = float(x["bid"]), float(x["ask"])
        if b <= 0 or a <= 0:
            bad += 1
            continue
        hit = None
        if d == 1:
            if b <= sl:
                hit = ("sl", b)
            elif b >= tp:
                hit = ("tp", tp)
        else:
            if a >= sl:
                hit = ("sl", a)
            elif a <= tp:
                hit = ("tp", tp)
        if hit:
            c = dict(tr)
            x_px = hit[1]
            c.update({"ev": "close", "x": x_px, "xt": int(ms / 1000), "xt_msc": ms, "win": hit[0] == "tp",
                      "r": round(d * (x_px - tr["e"]) / tr["risk"], 3),
                      "slip_r": round(d * (x_px - sl) / tr["risk"], 3) if hit[0] == "sl" else 0.0,
                      "bad_ticks": tr.get("bad_ticks", 0) + bad})
            return c
    tr["chk_msc"] = int(T[-1]["time_msc"])
    tr["bad_ticks"] = tr.get("bad_ticks", 0) + bad
    return None


ENG = {}       # sym -> Sym, alive for the daemon's life (the bot keeps its engine the same way)
DRIFT = {"files": ["not_checked_yet"], "t": 0.0}     # fail closed until the first check passes
STATS = {}     # sym -> counters shown on the page (missed / refused since start)


def process_symbol(sym, name, info, open_tr, seed):
    """new closed candles -> engine -> signals at fresh quotes; open trade -> tick exits"""
    S = ENG.get(sym)
    tr = open_tr.get(sym)
    if tr:
        done = tick_exit(tr, sym)
        if done:
            append(done)
            log("%s close %s r=%s slip=%s" % (sym, "win" if done["win"] else "loss", done["r"], done.get("slip_r")))
            open_tr.pop(sym, None)
            tr = None
    last2 = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 1, 2)
    if last2 is None or len(last2) == 0:
        return None
    if S is not None and int(last2[-1]["time"]) <= S.last:
        return None                      # no new closed candle
    R = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 1, FETCH)
    if R is None or len(R) < seed + 10:
        return None
    if S is None:
        S = Sym(sym)
        S.seed(R[-seed:])
        ENG[sym] = S
        log("%s seeded %d bars, trend %s" % (sym, seed, S.eng.trend))
        return R
    rows = None
    for j in range(len(R)):
        r = R[j]
        if int(r["time"]) <= S.last:
            continue
        sig = S.step(r)
        if not sig:
            continue
        cnt = STATS.setdefault(sym, {})
        if DRIFT.get("files"):
            cnt["code_drift"] = cnt.get("code_drift", 0) + 1
            append({"ev": "missed", "sym": sym, "sig_bar": int(r["time"]), "d": sig["d"], "why": "code_drift"})
            continue
        if open_tr.get(sym):
            cnt["position_open"] = cnt.get("position_open", 0) + 1
            continue
        if rows is None:
            rows = rows_of(R, info.digits)
        nt, why, meta = quote_entry(sym, info, R, j, sig, rows)
        if nt:
            nt.update({"ev": "open", "name": name})
            append(nt)
            open_tr[sym] = nt
            log("%s open d=%s e=%s sl=%s tp=%s lat=%ss" % (sym, nt["d"], nt["e"], nt["sl"], nt["tp"], nt["latency_s"]))
        else:
            cnt[why] = cnt.get(why, 0) + 1
            if why in ("late", "no_quote", "stale_quote", "price_through_stop"):
                rec = {"ev": "missed", "sym": sym, "sig_bar": int(r["time"]), "d": sig["d"], "why": why}
                rec.update(meta or {})
                append(rec)
            log("%s signal not taken: %s" % (sym, why))
    return R


CTRL_K = 40                      # streams per symbol and variant
CTRL_VARIANTS = ("coin", "trend")
CTRL_F = os.path.join(OUTD, "control_v3.jsonl")
WINDOW_F = os.path.join(OUTD, "protocol_window.json")
PBT = {}                         # sym -> pullback trend at the last state write (for the "trend" control)
CTRL = {}                        # stream id -> {"sym","var","next","pos"}
_RNG = None


def ctrl_params():
    try:
        return json.load(open(os.path.join(BUNDLE, "control_params.json"), encoding="utf-8"))
    except Exception:
        return {}


def ctrl_append(rec):
    rec.setdefault("engine", ENGINE_FWD)
    with open(CTRL_F, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


def ctrl_init():
    """the control streams; open control positions survive a restart (replayed on ticks)"""
    global _RNG
    import random
    _RNG = random.Random()
    P = ctrl_params()
    opened = {}
    try:
        for ln in open(CTRL_F, encoding="utf-8"):
            x = json.loads(ln)
            if x.get("ev") == "open":
                opened[x["sid"]] = x
            elif x.get("ev") == "close":
                opened.pop(x["sid"], None)
    except Exception:
        pass
    now = time.time()
    for sym, p in P.items():
        for var in CTRL_VARIANTS:
            for k in range(CTRL_K):
                sid = "%s:%s:%02d" % (sym, var, k)
                CTRL[sid] = {"sym": sym, "var": var, "pos": opened.get(sid),
                             "next": now + _RNG.expovariate(1.0 / max(60.0, p["mean_gap_s"]))}


def ctrl_step(sym, info):
    """open controls that are due, then judge the symbol's open control positions on its ticks"""
    P = ctrl_params().get(sym)
    if not P:
        return
    now = time.time()
    tk = None
    for sid, c in CTRL.items():
        if c["sym"] != sym or c["pos"] is not None or now < c["next"]:
            continue
        if DRIFT.get("files"):
            c["next"] = now + 60
            continue
        if tk is None:
            tk = mt5.symbol_info_tick(sym)
        last = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 1, 1)
        fresh = (tk is not None and tk.bid and tk.ask and now - tk.time_msc / 1000.0 <= QUOTE_MAX_AGE
                 and last is not None and len(last) and now - int(last[-1]["time"]) <= 15 * 60)
        if not fresh:                                  # market closed or no quote: try again later
            c["next"] = now + 60
            continue
        if c["var"] == "coin":
            d = 1 if _RNG.random() < 0.5 else -1
        else:
            d = PBT.get(sym, 0)
            if d not in (1, -1):
                c["next"] = now + 60
                continue
        px = float(tk.ask) if d == 1 else float(tk.bid)
        sp = float(tk.ask) - float(tk.bid)
        dist = _RNG.choice(P["risk_frac"]) * px
        if dist <= min_dist(sym, sp):
            c["next"] = now + 1
            continue
        RR = float(bot().RR)
        c["pos"] = {"sid": sid, "sym": sym, "var": c["var"], "d": d, "t": int(tk.time_msc / 1000), "t_msc": int(tk.time_msc),
                    "detect": round(now, 3), "latency_s": round(now - c["next"], 1), "quote_age_s": round(now - tk.time_msc / 1000.0, 1),
                    "e": px, "sl": px - d * dist, "tp": px + d * RR * dist, "risk": dist, "spread": sp,
                    "chk_msc": int(tk.time_msc), "ev": "open"}
        ctrl_append(dict(c["pos"]))
    opens = [c for c in CTRL.values() if c["sym"] == sym and c["pos"] is not None]
    if not opens:
        return
    t_from = min(c["pos"]["chk_msc"] for c in opens)
    T = mt5.copy_ticks_range(sym, datetime.fromtimestamp(t_from / 1000.0 + 0.001, tz=timezone.utc),
                             datetime.fromtimestamp(time.time(), tz=timezone.utc), mt5.COPY_TICKS_ALL)
    if T is None or len(T) == 0:
        return
    for c in opens:
        done = _walk(c["pos"], T)
        if done:
            ctrl_append(done)
            c["pos"] = None
            c["next"] = time.time() + _RNG.expovariate(1.0 / max(60.0, P["mean_gap_s"]))


def _walk(tr, T):
    """tick_exit's rule on an already-fetched tick array"""
    d, sl, tp = tr["d"], tr["sl"], tr["tp"]
    bad = 0
    for x in T:
        ms = int(x["time_msc"])
        if ms <= tr["chk_msc"]:
            continue
        b, a_ = float(x["bid"]), float(x["ask"])
        if b <= 0 or a_ <= 0:
            bad += 1
            continue
        hit = None
        if d == 1:
            hit = ("sl", b) if b <= sl else (("tp", tp) if b >= tp else None)
        else:
            hit = ("sl", a_) if a_ >= sl else (("tp", tp) if a_ <= tp else None)
        if hit:
            c = dict(tr)
            c.update({"ev": "close", "x": hit[1], "xt": int(ms / 1000), "xt_msc": ms, "win": hit[0] == "tp",
                      "r": round(d * (hit[1] - tr["e"]) / tr["risk"], 3),
                      "slip_r": round(d * (hit[1] - sl) / tr["risk"], 3) if hit[0] == "sl" else 0.0,
                      "bad_ticks": tr.get("bad_ticks", 0) + bad})
            return c
    tr["chk_msc"] = int(T[-1]["time_msc"])
    tr["bad_ticks"] = tr.get("bad_ticks", 0) + bad
    return None


def end_of_window(open_tr):
    """at the protocol window's end every open strategy AND control position is closed at the current quote
    (bid for a buy, ask for a sell), flagged eow - the same rule for both"""
    try:
        w = json.load(open(WINDOW_F, encoding="utf-8"))
    except Exception:
        return
    if time.time() < w["end"] or w.get("eow_done"):
        return
    for sym in list(open_tr):
        tr = open_tr[sym]
        tk = mt5.symbol_info_tick(sym)
        if tk is None:
            continue
        xp = float(tk.bid) if tr["d"] == 1 else float(tk.ask)
        c = dict(tr)
        c.update({"ev": "close", "x": xp, "xt": int(time.time()), "win": tr["d"] * (xp - tr["e"]) > 0,
                  "r": round(tr["d"] * (xp - tr["e"]) / tr["risk"], 3), "eow": True})
        append(c)
        open_tr.pop(sym, None)
    for c in CTRL.values():
        tr = c["pos"]
        if tr is None:
            continue
        tk = mt5.symbol_info_tick(tr["sym"])
        if tk is None:
            continue
        xp = float(tk.bid) if tr["d"] == 1 else float(tk.ask)
        cl = dict(tr)
        cl.update({"ev": "close", "x": xp, "xt": int(time.time()), "win": tr["d"] * (xp - tr["e"]) > 0,
                   "r": round(tr["d"] * (xp - tr["e"]) / tr["risk"], 3), "eow": True})
        ctrl_append(cl)
        c["pos"] = None
    w["eow_done"] = int(time.time())
    json.dump(w, open(WINDOW_F, "w", encoding="utf-8"))
    log("end of window %s: open positions closed at the quote (eow)" % w.get("protocol"))


def write_state(open_tr):
    rows_out = []
    for sym, name, cat in SYMBOLS:
        try:
            info = mt5.symbol_info(sym)
            S = ENG.get(sym)
            if info is None or S is None:
                rows_out.append({"sym": sym, "name": name, "cat": cat, "status": "no_data"})
                continue
            R = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 1, PB_BARS + 5)
            if R is None or len(R) < 100:
                rows_out.append({"sym": sym, "name": name, "cat": cat, "status": "no_data"})
                continue
            k = len(R) - 1
            rows = rows_of(R, info.digits)
            pt, _pc, _pl, L = pb_state(rows, k, info.digits)
            PBT[sym] = pt
            px = float(R[k]["close"])
            e = S.eng
            trig = (e.hi_v if e.trend == 1 else e.lo_v if e.trend == -1 else None)
            prot = (e.prot_lo[1] if (e.trend == 1 and e.prot_lo) else e.prot_hi[1] if (e.trend == -1 and e.prot_hi) else None)
            hr = R[max(0, k - 59):k + 1]
            rng = float(max(x["high"] for x in hr) - min(x["low"] for x in hr)) or 1e-9
            closed = time.time() - int(R[k]["time"]) > 15 * 60
            tr = open_tr.get(sym)
            near = None
            if tr:
                st = "trade"
            elif closed:
                st = "closed"
            elif pt == 0 or L is None:
                st = "no_trend"
            elif pt * (px - L) <= 0:
                st = "wrong_side"
                near = abs(px - L) / rng
            elif e.trend == pt and trig is not None:
                near = abs(trig - px) / rng
                st = "ready" if near <= 0.5 else ("soon" if near <= 2.0 else "far")
            else:
                st = "waiting_turn"
            sp = float(info.spread) * info.point
            row = {"sym": sym, "name": name, "cat": cat, "status": st, "px": px, "digits": info.digits,
                   "pb_trend": pt, "pb_bos": L, "trend": e.trend, "next_bos": trig, "inv": prot,
                   "near": round(near, 2) if near is not None else None,
                   "dist_pct": round(abs(trig - px) / px * 100, 3) if (trig is not None and px) else None,
                   "range_1h": rng, "spread": sp, "cost": round(sp / rng * 100, 1) if rng else None,
                   "updated": int(R[k]["time"]), "not_taken": STATS.get(sym, {})}
            if tr:
                tk = mt5.symbol_info_tick(sym)
                cur = (float(tk.bid) if tr["d"] == 1 else float(tk.ask)) if tk else px
                row["open"] = {"d": tr["d"], "e": tr["e"], "sl": tr["sl"], "tp": tr["tp"], "t": tr["t"],
                               "r_now": round(tr["d"] * (cur - tr["e"]) / tr["risk"], 2)}
            rows_out.append(row)
        except Exception as ex:
            log("%s state error %r" % (sym, ex))
            rows_out.append({"sym": sym, "name": name, "cat": cat, "status": "error"})
    try:
        cr = btc_corr()
        for row in rows_out:
            row["corr_btc"] = cr.get(row["sym"])
    except Exception as ex:
        log("corr error %r" % (ex,))
    st = {"updated": int(time.time()), "symbols": rows_out, "rr": float(bot().RR), "engine": ENGINE,
          "engine_fwd": ENGINE_FWD, "max_corr": MAX_CORR, "code_drift": DRIFT["files"]}
    json.dump(st, open(STATE + ".tmp", "w", encoding="utf-8"))
    os.replace(STATE + ".tmp", STATE)
    return st


def replay_open(open_tr):
    """after a restart: walk each open v3 trade through the ticks since its last check"""
    for sym in list(open_tr):
        tr = open_tr[sym]
        try:
            done = tick_exit(tr, sym)
            if done:
                done["replayed"] = True
                append(done)
                log("%s close (replayed after restart) %s r=%s" % (sym, "win" if done["win"] else "loss", done["r"]))
                open_tr.pop(sym, None)
        except Exception as ex:
            log("%s replay error %r" % (sym, ex))


def main():
    a = sys.argv[1:]
    bot()
    if not mt5.initialize(path=TERMINAL):
        raise SystemExit("MT5: %s" % (mt5.last_error(),))
    if "--backtest" in a:
        which = a[a.index("--backtest") + 1]
        days = float(a[a.index("--days") + 1]) if "--days" in a else 30.0
        syms = [s[0] for s in SYMBOLS] if which == "all" else [which]
        for s in syms:
            o = backtest(s, days)
            print(s, o.get("err") or o["summary"], "signals", o.get("signals"), "refused", o.get("refused"), "%ss" % o.get("secs"))
            sys.stdout.flush()
        mt5.shutdown()
        return
    # the v2 close-price history is kept apart, under its own name, never read as v3
    old = os.path.join(OUTD, "forward.jsonl")
    if os.path.exists(old) and not os.path.exists(FWD_V2):
        os.replace(old, FWD_V2)
        log("v2 close-price records moved to forward_v2_close.jsonl (kept apart from v3)")
    feed()                                # load the whole engine now, so isolation() sees every module
    DRIFT["files"] = drift()
    log("startup check: %s" % ("OK - bundle verified and isolated" if not DRIFT["files"] else "BLOCKED %s" % DRIFT["files"]))
    open_tr = load_open()
    replay_open(open_tr)
    ctrl_init()
    seed = int(bot().SEED_BARS)
    log("scanner start (%s / forward %s), %d symbols, poll %ss" % (ENGINE, ENGINE_FWD, len(SYMBOLS), POLL_S))
    last_state = 0.0
    while True:
        t0 = time.time()
        try:
            for sym, name, cat in SYMBOLS:
                info = mt5.symbol_info(sym)
                if info is None:
                    continue
                if not info.visible:
                    mt5.symbol_select(sym, True)
                try:
                    process_symbol(sym, name, info, open_tr, seed)
                except Exception as ex:
                    log("%s error %r" % (sym, ex))
                try:
                    ctrl_step(sym, info)
                except Exception as ex:
                    log("%s control error %r" % (sym, ex))
            end_of_window(open_tr)
            if time.time() - last_state >= 60 or "--once" in a:
                d0 = DRIFT["files"]
                DRIFT["files"] = drift()
                if DRIFT["files"] and not d0:
                    log("GUARD BLOCKED: %s - no new virtual trades (strategy and controls)" % DRIFT["files"])
                write_state(open_tr)
                last_state = time.time()
                with open(HB, "a", encoding="utf-8") as f:       # one line a minute: uptime for the protocol
                    f.write(json.dumps({"t": int(time.time()), "open": len(open_tr), "drift": DRIFT["files"]}) + "\n")
        except Exception as ex:
            log("pass error %r" % (ex,))
            try:
                mt5.shutdown(); time.sleep(5); mt5.initialize(path=TERMINAL)
            except Exception:
                pass
        if "--once" in a:
            st = json.load(open(STATE, encoding="utf-8"))
            for r in st["symbols"]:
                print(r["sym"].ljust(8), r["status"].ljust(12), r.get("pb_trend"), r.get("trend"), r.get("near"), r.get("dist_pct"))
            mt5.shutdown()
            return
        time.sleep(max(1.0, POLL_S - (time.time() - t0)))


if __name__ == "__main__":
    main()
