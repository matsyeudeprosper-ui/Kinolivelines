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
sys.path.insert(0, DIR)
OUTD = os.path.join(DIR, "scanner")
os.makedirs(OUTD, exist_ok=True)
STATE = os.path.join(OUTD, "state.json")
FWD = os.path.join(OUTD, "forward.jsonl")
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
        p = os.path.join(DIR, "owl_chart_feed.py")
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
def backtest(sym, days):
    info = mt5.symbol_info(sym)
    if info is None:
        return {"sym": sym, "err": "symbol not found"}
    mt5.symbol_select(sym, True)
    seed = int(bot().SEED_BARS)
    n = PB_BARS + int(days * 1440) + 10
    R = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 1, n)
    if R is None or len(R) < PB_BARS + 100:
        return {"sym": sym, "err": "not enough history (%s bars)" % (0 if R is None else len(R))}
    t0 = time.time()
    rows = rows_of(R, info.digits)
    S = Sym(sym)
    S.seed(R[PB_BARS - seed:PB_BARS])          # the bot seeds with SEED_BARS closed bars
    trades, refused, open_tr, sigs = [], {}, None, 0
    for k in range(PB_BARS, len(R)):
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
    out = {"sym": sym, "days": days, "engine": ENGINE, "from": int(R[PB_BARS]["time"]), "to": int(R[-1]["time"]),
           "built": int(time.time()), "secs": round(time.time() - t0, 1), "signals": sigs, "refused": refused,
           "summary": summary(trades), "trades": trades[-500:]}
    json.dump(out, open(os.path.join(OUTD, "backtest_%s.json" % sym), "w", encoding="utf-8"))
    return out


# ------------------------------------------------------------------ forward
def load_open():
    op = {}
    try:
        for ln in open(FWD, encoding="utf-8"):
            x = json.loads(ln)
            if x.get("engine") != ENGINE:
                continue
            if x.get("ev") == "open":
                op[x["sym"]] = x
            elif x.get("ev") == "close":
                op.pop(x["sym"], None)
    except Exception:
        pass
    return op


def append(rec):
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


ENG = {}       # sym -> Sym, alive for the daemon's life (the bot keeps its engine the same way)


def scan_once(open_tr):
    rows_out = []
    seed = int(bot().SEED_BARS)
    for sym, name, cat in SYMBOLS:
        try:
            info = mt5.symbol_info(sym)
            if info is None:
                continue
            if not info.visible:
                mt5.symbol_select(sym, True)
            R = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 1, FETCH)      # closed bars only
            if R is None or len(R) < seed + 10:
                rows_out.append({"sym": sym, "name": name, "cat": cat, "status": "no_data"})
                continue
            k = len(R) - 1
            S = ENG.get(sym)
            if S is None:
                S = Sym(sym)
                S.seed(R[-seed:])
                ENG[sym] = S
                log("%s seeded %d bars, trend %s" % (sym, seed, S.eng.trend))
            rows = None
            tr = open_tr.get(sym)
            for j in range(len(R)):
                r = R[j]
                if int(r["time"]) <= S.last:
                    continue
                if tr:
                    done = step_trade(tr, r, info.point)
                    if done:
                        done["ev"] = "close"
                        append(done)
                        log("%s close %s r=%s" % (sym, "win" if done["win"] else "loss", done["r"]))
                        open_tr.pop(sym, None)
                        tr = None
                sig = S.step(r)
                if sig and not tr:
                    if rows is None:
                        rows = rows_of(R, info.digits)
                    nt, why = try_entry(sym, info, R, j, sig, rows)
                    if nt:
                        nt.update({"ev": "open", "name": name})
                        append(nt)
                        open_tr[sym] = nt
                        tr = nt
                        log("%s open d=%s e=%s sl=%s tp=%s" % (sym, nt["d"], nt["e"], nt["sl"], nt["tp"]))
                    else:
                        log("%s signal refused: %s" % (sym, why))
            closed = time.time() - int(R[k]["time"]) > 15 * 60
            if rows is None:
                rows = rows_of(R, info.digits)
            pt, _pc, _pl, L = pb_state(rows, k, info.digits)
            px = float(R[k]["close"])
            e = S.eng
            trig = (e.hi_v if e.trend == 1 else e.lo_v if e.trend == -1 else None)
            prot = (e.prot_lo[1] if (e.trend == 1 and e.prot_lo) else e.prot_hi[1] if (e.trend == -1 and e.prot_hi) else None)
            hr = R[max(0, k - 59):k + 1]
            rng = float(max(x["high"] for x in hr) - min(x["low"] for x in hr)) or 1e-9
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
                   "near": round(near, 2) if near is not None else None, "range_1h": rng, "spread": sp,
                   "cost": round(sp / rng * 100, 1) if rng else None, "updated": int(R[k]["time"])}
            if tr:
                cur = px if tr["d"] == 1 else px + sp
                row["open"] = {"d": tr["d"], "e": tr["e"], "sl": tr["sl"], "tp": tr["tp"], "t": tr["t"],
                               "r_now": round(tr["d"] * (cur - tr["e"]) / tr["risk"], 2)}
            rows_out.append(row)
        except Exception as ex:
            log("%s error %r" % (sym, ex))
            rows_out.append({"sym": sym, "name": name, "cat": cat, "status": "error"})
    try:
        cr = btc_corr()
        for row in rows_out:
            row["corr_btc"] = cr.get(row["sym"])
    except Exception as ex:
        log("corr error %r" % (ex,))
    st = {"updated": int(time.time()), "symbols": rows_out, "rr": float(bot().RR), "engine": ENGINE,
          "max_corr": MAX_CORR}
    json.dump(st, open(STATE + ".tmp", "w", encoding="utf-8"))
    os.replace(STATE + ".tmp", STATE)
    return st


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
    open_tr = load_open()
    if "--once" in a:
        st = scan_once(open_tr)
        for r in st["symbols"]:
            print(r["sym"].ljust(8), r["status"].ljust(12), r.get("pb_trend"), r.get("trend"), r.get("near"), r.get("cost"))
        mt5.shutdown()
        return
    log("scanner start (%s), %d symbols" % (ENGINE, len(SYMBOLS)))
    while True:
        t0 = time.time()
        try:
            scan_once(open_tr)
        except Exception as ex:
            log("pass error %r" % (ex,))
            try:
                mt5.shutdown(); time.sleep(5); mt5.initialize(path=TERMINAL)
            except Exception:
                pass
        time.sleep(max(5.0, 60.0 - (time.time() - t0)))


if __name__ == "__main__":
    main()
