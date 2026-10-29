"""Ghost mode (owner 2026-10-19 items 4 and 8): a robot trades with pretend money on LIVE candles (ghost_feed.py), candle
by candle, with the same pieces as its tests (robot_demo's signals / filters / stops / exits); two ghosts in one
conversation = a duel. advance(ghost, rules, rr) moves a ghost to the newest closed candle and returns the events
(opened / closed) so Kino can comment them. Pure bookkeeping - no order, no account."""
import json, os, time

import numpy as np

import robot_demo as RD
import robot_expr as X

CACHE = RD.CACHE
MAX_TRADE_MIN = 1440


def live_bars(market):
    m = (market or "BTCUSD").upper()
    try:
        meta = json.load(open(os.path.join(CACHE, "live_%s.json" % m), encoding="utf-8"))
        if time.time() - float(meta["at"]) > 600:
            return None, None
        return np.load(os.path.join(CACHE, "live_%s.npz" % m))["R"], float(meta["k"])
    except Exception:
        return None, None


def want_markets(markets):
    """tell ghost_feed.py which markets to keep fresh (and start it if it is not running)"""
    import subprocess, sys
    os.makedirs(CACHE, exist_ok=True)
    json.dump(sorted(set(m.upper() for m in markets)), open(os.path.join(CACHE, "ghost_syms.json"), "w"))
    lock = os.path.join(CACHE, "ghost_feed.lock")
    if markets and not (os.path.exists(lock) and time.time() - os.path.getmtime(lock) < 180):
        py = sys.executable.replace("python.exe", "pythonw.exe")
        subprocess.Popen([py if os.path.exists(py) else sys.executable, os.path.join(RD.HERE, "ghost_feed.py")],
                         cwd=RD.HERE, creationflags=0x08000000 | 0x00004000, close_fds=True)


def _eyes(R):
    S = RD._struct_class()()
    S.quiet = True
    n = len(R); d = np.zeros(n, np.int8); fl = np.zeros(n, bool); slp = np.full(n, np.nan)
    for i in range(n):
        pt = S.trend
        sg = S.step(int(R["time"][i]), float(R["open"][i]), float(R["high"][i]), float(R["low"][i]), float(R["close"][i]))
        if sg:
            d[i] = sg[0]; slp[i] = float(sg[1]); fl[i] = S.trend != pt
    return {"d": d, "flip": fl, "slp": slp}


def advance(g, rules, rr=0.8):
    """move the ghost to the newest closed candle; returns events [{"kind": "opened"|"closed", ...}]"""
    R, k = live_bars(g.get("market"))
    if R is None:
        return []
    T = R["time"].astype(np.int64)
    last = int(g.get("last_t") or 0)
    if not last:                                    # a new ghost starts from now, it never trades the past
        g["last_t"] = int(T[-1])
        return []
    new = np.flatnonzero(T > last)
    if not len(new):
        return []
    eyes = _eyes(R)
    B = RD._bars(R, eyes)
    cache = {}
    sig = {i: (d, slp) for i, d, slp in RD._signals(rules, R, eyes, B)}
    ex = rules.get("exit") or {}
    tgt = ex.get("target", rr) if ex else rr
    xs_b, xs_s = ex.get("close_buy"), ex.get("close_sell")
    out = []
    for j in new:
        j = int(j)
        h, l, c = float(R["high"][j]), float(R["low"][j]), float(R["close"][j])
        o = g.get("open")
        if o:
            d, sl, tp = o["d"], o["sl"], o.get("tp")
            why = None; xp = None
            if (d == 1 and l <= sl) or (d == -1 and h >= sl):
                why, xp = ("be" if o.get("be") else "stop"), sl
            elif tp is not None and ((d == 1 and h >= tp) or (d == -1 and l <= tp)):
                why, xp = "target", tp
            else:
                src = xs_b if d == 1 else xs_s
                if src:
                    if src not in cache:
                        cache[src] = X.truth(src, B)
                    if cache[src][j]:
                        why, xp = "formula", c
                if not why and ex.get("time_min") and (int(T[j]) - o["t_in"]) / 60 >= int(ex["time_min"]):
                    why, xp = "time", c
                if not why and (int(T[j]) - o["t_in"]) / 60 >= MAX_TRADE_MIN:
                    why, xp = "time", c
                if not why and ex.get("breakeven_at") and not o.get("be") and d * (c - o["e"]) >= float(ex["breakeven_at"]) * o["risk"]:
                    o["sl"] = o["e"]; o["be"] = True
                if not why and ex.get("breakeven_frac") and not o.get("be") and tp is not None and d * (tp - o["e"]) > 0 \
                        and d * (c - o["e"]) >= float(ex["breakeven_frac"]) * d * (tp - o["e"]):
                    o["sl"] = o["e"]; o["be"] = True
            if why:
                r = round(d * (xp - o["e"]) / o["risk"], 2)
                tr = {"t_in": o["t_in"], "t_out": int(T[j]), "d": d, "e": round(o["e"] / k, 5), "x": round(xp / k, 5), "why": why, "r": r}
                g.setdefault("trades", []).append(tr)
                g["trades"] = g["trades"][-200:]
                g["open"] = None
                out.append(dict(tr, kind="closed"))
        elif j in sig:
            d, slp = sig[j]
            if RD._ok_filters(rules, j, d, R, B, cache):
                sl = RD._stop(rules, j, d, slp, R, B, cache)
                if sl == sl and d * (c - sl) > 0:
                    risk = abs(c - sl)
                    g["open"] = {"t_in": int(T[j]), "d": d, "e": c, "sl": sl, "tp": (c + d * float(tgt) * risk) if tgt else None,
                                 "risk": risk, "e_show": round(c / k, 5), "sl_show": round(sl / k, 5)}
                    out.append({"kind": "opened", "t_in": int(T[j]), "d": d, "e": round(c / k, 5), "sl": round(sl / k, 5),
                                "tp": round((c + d * float(tgt) * risk) / k, 5) if tgt else None})
        g["last_t"] = int(T[j])
    return out


def summary(g):
    tr = g.get("trades") or []
    won = sum(1 for t in tr if t["r"] > 0)
    return {"trades": len(tr), "won": won, "won_pct": round(100.0 * won / len(tr), 1) if tr else None,
            "sum_r": round(sum(t["r"] for t in tr), 2), "open": bool(g.get("open")),
            "days": round((time.time() - float(g.get("started") or time.time())) / 86400.0, 1)}
