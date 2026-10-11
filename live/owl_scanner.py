"""owl_scanner.py - the setup scanner (owner 2026-10-11).

"Make the market page a place where the app scans other symbols and shows
which have a setup ready. First version: virtual trades only, keep records,
and see whether the backtests of the new symbols match the forward test."

WHAT IT DOES
  Every minute, for each symbol in SYMBOLS, it reads the last WINDOW M1 bars
  (read only - this file never sends an order) and runs the SAME structure
  engine the BTC chart uses (owl_chart_feed.build / engine / pullback_view),
  then applies the robot's core trend-following rule:

    pullback trend up   -> only a BUY BOS of the minute structure, and only
                           while price is above the pullback chart's last BOS
    pullback trend down -> the mirror image

  A virtual trade opens at the close of the breaking candle (ask for a buy),
  its stop is the structure's protected level, its target 0.8 x the risk -
  the robot's numbers. It closes on the first M1 bar that touches either
  (both on one bar = counted as a LOSS). Results are in R (result / risk), so
  gold, an index and a currency are comparable without contract sizes.

  It is the robot's CORE setup, not the whole robot: no weather brake, no
  recovery, no lot sizing. That is said on the page too.

THE SAME FUNCTION does the forward test and the backtest (--backtest), so a
gap between the two is the market, not two codes.

Files (live/scanner/):
  state.json            what each symbol is doing now (the page reads it)
  forward.jsonl         every virtual trade, opened and closed, forward
  backtest_<SYM>.json   the backtest of each symbol (same rule, past bars)

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
os.makedirs(OUTD, exist_ok=True)
STATE = os.path.join(OUTD, "state.json")
FWD = os.path.join(OUTD, "forward.jsonl")
LOGF = os.path.join(OUTD, "scanner.log")
# the chart feed's own demo terminal; we ATTACH to it (no login call), so the
# account it runs is never switched, and we only ever READ prices
TERMINAL = r"C:\NestTerminals\u476954287\terminal64.exe"

# cheapest symbols of the broker's cost census (spread vs the hourly move,
# study/cost_census.csv - BTC scores 3.3), spread over gold, oil, indices,
# currencies and one more crypto. BTCUSD is the REFERENCE: the robot's own.
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
MAX_CORR = 0.5          # a symbol moving with BTC above this is flagged (and should not be added)
WINDOW = 8000          # M1 bars per evaluation - the chart feed's own window
RR = 0.8               # the robot's target
MIN_RISK_SPREADS = 3.0  # a stop closer than 3 spreads is noise (the robot's S_MIN_DIST idea)


def log(m):
    try:
        with open(LOGF, "a", encoding="utf-8") as f:
            f.write(datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ ") + m + "\n")
    except Exception:
        pass


_F = None


def feed():
    """the chart feed's engine, imported as a module (its main() is not run)"""
    global _F
    if _F is None:
        p = os.path.join(DIR, "owl_chart_feed.py")
        sp = importlib.util.spec_from_file_location("owl_chart_feed_scan", p)
        m = importlib.util.module_from_spec(sp)
        sp.loader.exec_module(m)
        _F = m
    return _F


def scale_of(digits):
    """the engine rounds to 2 decimals (it was written for BTC). Prices are
    multiplied so 2 decimals keep the symbol's full precision, and divided
    back for display - the engine only compares prices, so the result is
    the same structure."""
    return 10 ** max(0, int(digits) - 2)


def rows_of(R, digits):
    s = scale_of(digits)
    return [{"time": int(r["time"]), "open": float(r["open"]) * s, "high": float(r["high"]) * s,
             "low": float(r["low"]) * s, "close": float(r["close"]) * s} for r in R]


def evaluate(R, k, digits, rows=None):
    """The structure at bar k (R[k] = the last CLOSED bar). Returns a dict:
    t, px, pb_trend, pb_bos, trend, next_bos, inv, signal (None or
    {d, level, sl}) - all prices in the symbol's own units."""
    F = feed()
    s = scale_of(digits)
    g0 = max(0, k - WINDOW + 1)
    win = rows[g0:k + 1] if rows is not None else rows_of(R[g0:k + 1], digits)
    kept = F.build(win)
    out = {"t": int(R[k]["time"]), "px": float(R[k]["close"]), "pb_trend": 0, "pb_bos": None,
           "trend": 0, "next_bos": None, "inv": None, "signal": None}
    if len(kept) < 5:
        return out
    bk = []
    (dots, marks, trend, choch, nxt, inv, nxt_t, inv_t, dr,
     flp, flp_t, fdir) = F.engine(kept, brk_out=bk)
    out["trend"] = int(trend or 0)
    out["next_bos"] = (nxt / s) if nxt else None
    out["inv"] = (inv / s) if inv else None
    d2 = [x for x in dots if x[2] == trend] if trend else dots
    pb = F.pullback_view(kept, d2, marks, bk, write=False) or {}
    pt = int(pb.get("trend") or 0)
    pbk = pb.get("breaks") or []
    L = float(pbk[-1][2]) / s if pbk else None
    out["pb_trend"], out["pb_bos"] = pt, L
    # a fresh minute-structure BOS on THIS candle, with the background trend,
    # beyond the pullback chart's last BOS: the robot's trend-following entry
    if bk and int(bk[-1][0]) == int(kept[-1][0]) == int(R[k]["time"]) and pt in (1, -1) and int(bk[-1][1]) == pt \
            and L is not None and inv:
        px = float(R[k]["close"])
        if pt * (px - L) > 0:
            out["signal"] = {"d": pt, "level": float(bk[-1][2]) / s, "sl": inv / s}
    return out


def spread_px(r, point):
    try:
        return float(r["spread"]) * point
    except Exception:
        return 0.0


def open_trade(sym, ev, r, point):
    """the virtual trade from a signal, or a refusal reason"""
    d, sl = ev["signal"]["d"], ev["signal"]["sl"]
    sp = spread_px(r, point)
    e = float(r["close"]) + (sp if d == 1 else 0.0)        # bars are BID: a buy pays the spread
    risk = d * (e - sl)
    if risk <= 0:
        return None, "stop on the wrong side"
    if sp > 0 and risk < MIN_RISK_SPREADS * sp:
        return None, "stop too close to the spread"
    tp = e + d * RR * risk
    return {"sym": sym, "d": d, "t": int(r["time"]), "e": e, "sl": sl, "tp": tp, "risk": risk,
            "spread": sp, "level": ev["signal"]["level"]}, None


def step_trade(tr, r, point):
    """advance an open virtual trade by one M1 bar; returns the closed trade or None"""
    sp = spread_px(r, point)
    hi, lo = float(r["high"]), float(r["low"])
    if tr["d"] == 1:            # buy closes at BID
        hit_sl, hit_tp = lo <= tr["sl"], hi >= tr["tp"]
    else:                       # sell closes at ASK
        hit_sl, hit_tp = hi + sp >= tr["sl"], lo + sp <= tr["tp"]
    if not (hit_sl or hit_tp):
        return None
    win = hit_tp and not hit_sl            # both on one bar = a loss (we cannot see the order)
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
    n = WINDOW + int(days * 1440) + 10
    R = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 1, n)      # from 1: closed bars only
    if R is None or len(R) < WINDOW + 100:
        return {"sym": sym, "err": "not enough history (%s bars)" % (0 if R is None else len(R))}
    F = feed()
    s = scale_of(info.digits)
    trades, refused, open_tr = [], {}, None
    ALL = rows_of(R, info.digits)          # converted once, sliced per evaluation
    t0 = time.time()
    # the engine can only see a new BOS on a bar whose close is KEPT by the
    # silence filter, so only those bars are evaluated (same answer, faster)
    ref_h = ref_l = None
    for k in range(len(R)):
        r = R[k]
        h, l, c = float(r["high"]) * s, float(r["low"]) * s, float(r["close"]) * s
        is_kept = ref_h is None or c > ref_h or c < ref_l
        if is_kept:
            ref_h, ref_l = h, l
        if k < WINDOW:
            continue
        if open_tr is not None:
            done = step_trade(open_tr, r, info.point)
            if done:
                trades.append(done)
                open_tr = None
            continue
        if not is_kept:
            continue
        ev = evaluate(R, k, info.digits, rows=ALL)
        if ev["signal"]:
            tr, why = open_trade(sym, ev, r, info.point)
            if tr:
                open_tr = tr
            else:
                refused[why] = refused.get(why, 0) + 1
    out = {"sym": sym, "days": days, "from": int(R[WINDOW]["time"]), "to": int(R[-1]["time"]),
           "built": int(time.time()), "secs": round(time.time() - t0, 1), "refused": refused,
           "summary": summary(trades), "trades": trades[-400:]}
    json.dump(out, open(os.path.join(OUTD, "backtest_%s.json" % sym), "w", encoding="utf-8"))
    return out


# ------------------------------------------------------------------ forward
def load_open():
    """open virtual trades survive a restart: replay forward.jsonl"""
    op = {}
    try:
        for ln in open(FWD, encoding="utf-8"):
            x = json.loads(ln)
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
    """hourly-return correlation of each symbol with BTCUSD over ~60 days, refreshed every 6 h"""
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


def scan_once(open_tr, last_eval):
    rows = []
    for sym, name, cat in SYMBOLS:
        try:
            info = mt5.symbol_info(sym)
            if info is None:
                continue
            if not info.visible:
                mt5.symbol_select(sym, True)
            R = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 1, WINDOW + 200)
            if R is None or len(R) < 300:
                rows.append({"sym": sym, "name": name, "cat": cat, "status": "no_data"})
                continue
            k = len(R) - 1
            last_t = int(R[k]["time"])
            closed = time.time() - last_t > 15 * 60      # no new bar for 15 min: market closed
            # move an open trade through every bar it has not seen yet
            tr = open_tr.get(sym)
            if tr:
                for r in R:
                    if int(r["time"]) <= int(tr.get("seen", tr["t"])):
                        continue
                    done = step_trade(tr, r, info.point)
                    tr["seen"] = int(r["time"])
                    if done:
                        done["ev"] = "close"
                        append(done)
                        log("%s close %s r=%s" % (sym, "win" if done["win"] else "loss", done["r"]))
                        open_tr.pop(sym, None)
                        tr = None
                        break
            ev = evaluate(R, k, info.digits)
            # a signal is acted on once per bar
            if ev["signal"] and not tr and last_eval.get(sym) != last_t and not closed:
                nt, why = open_trade(sym, ev, R[k], info.point)
                if nt:
                    nt.update({"ev": "open", "seen": last_t, "name": name})
                    append(nt)
                    open_tr[sym] = nt
                    tr = nt
                    log("%s open d=%s e=%s sl=%s tp=%s" % (sym, nt["d"], nt["e"], nt["sl"], nt["tp"]))
                else:
                    log("%s signal refused: %s" % (sym, why))
            last_eval[sym] = last_t
            # how far price is from the next trigger, in units of the last hour's range
            hr = R[max(0, k - 59):k + 1]
            rng = float(max(x["high"] for x in hr) - min(x["low"] for x in hr)) or 1e-9
            pt, L, px = ev["pb_trend"], ev["pb_bos"], ev["px"]
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
            elif ev["trend"] == pt and ev["next_bos"]:
                near = abs(ev["next_bos"] - px) / rng
                st = "ready" if near <= 0.5 else ("soon" if near <= 2.0 else "far")
            else:
                st = "waiting_turn"
            sp = float(info.spread) * info.point
            row = {"sym": sym, "name": name, "cat": cat, "status": st, "px": px, "digits": info.digits,
                   "pb_trend": pt, "pb_bos": L, "trend": ev["trend"], "next_bos": ev["next_bos"],
                   "inv": ev["inv"], "near": round(near, 2) if near is not None else None,
                   "range_1h": rng, "spread": sp, "cost": round(sp / rng * 100, 1) if rng else None,
                   "updated": last_t}
            if tr:
                cur = float(R[k]["close"]) if tr["d"] == 1 else float(R[k]["close"]) + sp
                row["open"] = {"d": tr["d"], "e": tr["e"], "sl": tr["sl"], "tp": tr["tp"], "t": tr["t"],
                               "r_now": round(tr["d"] * (cur - tr["e"]) / tr["risk"], 2)}
            rows.append(row)
        except Exception as e:
            log("%s error %r" % (sym, e))
            rows.append({"sym": sym, "name": name, "cat": cat, "status": "error"})
    try:
        cr = btc_corr()
        for row in rows:
            row["corr_btc"] = cr.get(row["sym"])
    except Exception as e:
        log("corr error %r" % (e,))
    st = {"updated": int(time.time()), "symbols": rows, "rr": RR, "window": WINDOW, "max_corr": MAX_CORR}
    json.dump(st, open(STATE + ".tmp", "w", encoding="utf-8"))
    os.replace(STATE + ".tmp", STATE)
    return st


def main():
    a = sys.argv[1:]
    if not mt5.initialize(path=TERMINAL):
        raise SystemExit("MT5: %s" % (mt5.last_error(),))
    if "--backtest" in a:
        which = a[a.index("--backtest") + 1]
        days = float(a[a.index("--days") + 1]) if "--days" in a else 30.0
        syms = [s[0] for s in SYMBOLS] if which == "all" else [which]
        for s in syms:
            o = backtest(s, days)
            print(s, o.get("err") or o["summary"], "refused", o.get("refused"), "%ss" % o.get("secs"))
            sys.stdout.flush()
        mt5.shutdown()
        return
    open_tr, last_eval = load_open(), {}
    if "--once" in a:
        st = scan_once(open_tr, last_eval)
        for r in st["symbols"]:
            print(r["sym"].ljust(8), r["status"].ljust(12), r.get("pb_trend"), r.get("near"), r.get("cost"))
        mt5.shutdown()
        return
    log("scanner start, %d symbols" % len(SYMBOLS))
    while True:
        t0 = time.time()
        try:
            scan_once(open_tr, last_eval)
        except Exception as e:
            log("pass error %r" % (e,))
            try:
                mt5.shutdown(); time.sleep(5); mt5.initialize(path=TERMINAL)
            except Exception:
                pass
        time.sleep(max(5.0, 60.0 - (time.time() - t0)))


if __name__ == "__main__":
    main()
