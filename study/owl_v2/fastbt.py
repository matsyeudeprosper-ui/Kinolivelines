"""fastbt.py (2026-10-30, Owl v2) - a fast, honest bar backtester on the saved BTCUSD M1 archive (Valere's broker feed).

Fills: entry at the open of the M1 bar after the signal bar closes; a buy pays the ask (bid + that bar's spread),
a sell's exits are on the ask. Stop and target are checked on M1 high/low; when both are inside one bar the STOP
is taken (pessimistic). Money at a fixed 0.01 lot ($ = price move x 0.01). One trade at a time.
It is a screen: a winner must then be checked on ticks (study/owl_v2/tickcheck.py) before anyone believes it.
"""
import os
from datetime import datetime, timezone
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.dirname(HERE)
LOT = 0.01
BIG = 10 ** 9
_M1 = None


def m1():
    """Dec 2025 .. Oct 2026 M1 bars as plain arrays (t, o, h, l, c, sp in price units)"""
    global _M1
    if _M1 is None:
        P = [os.path.join(STUDY, "ticks_archive_BTCUSD", "bars_%s.npz" % k) for k in
             ["2025-12"] + ["2026-%02d" % m for m in range(1, 10)]] + [os.path.join(STUDY, "bars_u224016179.npz")]
        R = np.concatenate([np.load(p)["R"] for p in P])
        R = R[np.unique(R["time"], return_index=True)[1]]
        _M1 = {"t": R["time"].astype(np.int64), "o": R["open"].astype(float), "h": R["high"].astype(float),
               "l": R["low"].astype(float), "c": R["close"].astype(float), "sp": R["spread"].astype(float) * 0.01}
    return _M1


def agg(minutes):
    """M1 -> bars of `minutes` (aligned on UTC); returns arrays plus `ix` = index of the M1 bar that opens right after each bar closes"""
    M = m1()
    if minutes == 1:
        b = dict(M)
        b["ix"] = np.arange(1, len(M["t"]) + 1)
        b["tc"] = M["t"] + 60
        return b
    k = M["t"] // (minutes * 60)
    st = np.flatnonzero(np.r_[True, k[1:] != k[:-1]])
    en = np.r_[st[1:], len(k)]
    b = {"t": M["t"][st], "o": M["o"][st], "c": M["c"][en - 1],
         "h": np.maximum.reduceat(M["h"], st), "l": np.minimum.reduceat(M["l"], st)}
    b["tc"] = (k[st] + 1) * minutes * 60                        # the bar's close time
    b["ix"] = np.searchsorted(M["t"], b["tc"])                  # first M1 bar at/after the close
    return b


def atr(b, n=14):
    pc = np.r_[b["c"][0], b["c"][:-1]]
    tr = np.maximum(b["h"] - b["l"], np.maximum(abs(b["h"] - pc), abs(b["l"] - pc)))
    a = np.empty_like(tr)
    a[0] = tr[0]
    al = 1.0 / n
    for i in range(1, len(tr)):
        a[i] = a[i - 1] + al * (tr[i] - a[i - 1])
    return a


def ema(x, n):
    a = np.empty_like(x)
    a[0] = x[0]
    al = 2.0 / (n + 1)
    for i in range(1, len(x)):
        a[i] = a[i - 1] + al * (x[i] - a[i - 1])
    return a


def simulate(sig, max_hold_min=1440, be_frac=0.0, start=None, end=None):
    """sig: list of (m1_index, dir, stop_dist, tp_dist) in time order. Returns trades list of dicts."""
    M = m1()
    t, o, h, l, c, sp = M["t"], M["o"], M["h"], M["l"], M["c"], M["sp"]
    n = len(t)
    out = []
    busy = -1
    for (i, d, sd, td) in sig:
        if i <= busy or i >= n - 2:
            continue
        if start is not None and t[i] < start:
            continue
        if end is not None and t[i] >= end:
            break
        s0 = sp[i]
        e = o[i] + (s0 if d == 1 else 0.0)                     # buy pays the ask
        sl, tp = e - d * sd, e + d * td
        j1 = min(n, i + max_hold_min)
        H, L, S = h[i:j1], l[i:j1], sp[i:j1]
        if d == 1:                                             # buy exits on the bid
            hit_sl, hit_tp = L <= sl, H >= tp
        else:                                                  # sell exits on the ask
            hit_sl, hit_tp = H + S >= sl, L + S <= tp
        ks, kt = np.flatnonzero(hit_sl), np.flatnonzero(hit_tp)
        js = ks[0] if len(ks) else BIG
        jt = kt[0] if len(kt) else BIG
        stop_px = sl
        if be_frac > 0:                                        # stop to entry once price went be_frac of the way to the target
            lvl = e + d * be_frac * td
            ka = np.flatnonzero((H >= lvl) if d == 1 else (L + S <= lvl))
            if len(ka) and ka[0] < min(js, jt):                # armed before anything closed it; the bar after arming can hit entry
                a = ka[0]
                hb = np.flatnonzero((L[a + 1:] <= e) if d == 1 else (H[a + 1:] + S[a + 1:] >= e))
                jb = a + 1 + hb[0] if len(hb) else BIG
                if jb < js:
                    js, stop_px = jb, e
        if js == BIG and jt == BIG:
            jx = j1 - 1 - i
            px = c[i + jx] + (0.0 if d == 1 else S[jx])
            pts, why = d * (px - e), "time"
        elif js <= jt:
            jx = js
            pts, why = d * (stop_px - e), ("be" if stop_px == e else "sl")
        else:
            jx = jt
            pts, why = td, "tp"
        out.append({"t": int(t[i]), "tx": int(t[i + jx]), "d": d, "pts": pts, "usd": pts * LOT, "why": why, "sd": sd, "sp": s0})
        busy = i + jx
    return out


def report(tr, label="", quiet=False):
    """month nets, weeks, days with a trade"""
    M = m1()
    mo, wk, dy = {}, {}, set()
    for x in tr:
        g = datetime.fromtimestamp(x["t"], tz=timezone.utc)
        mo.setdefault(g.strftime("%Y-%m"), []).append(x["usd"])
        wk.setdefault(g.strftime("%G-W%V"), []).append(x["usd"])
        dy.add(g.strftime("%Y-%m-%d"))
    months = ["2026-%02d" % m for m in range(1, 11)]
    mn = {m: round(sum(mo.get(m, [])), 2) for m in months}
    nd = len({datetime.fromtimestamp(int(t), tz=timezone.utc).strftime("%Y-%m-%d") for t in M["t"][M["t"] >= 1767225600][::1440]})
    W = {k: sum(v) for k, v in wk.items() if k >= "2026-W01"}
    r = {"label": label, "n": len(tr), "net": round(sum(mn.values()), 2), "months_up": int(sum(v > 0 for v in mn.values())),
         "weeks_up": sum(v > 0 for v in W.values()), "weeks": len(W), "days_traded": len([d for d in dy if d >= "2026-01-01"]), "days": nd,
         "wr": round(100 * np.mean([x["pts"] > 0 for x in tr]), 1) if tr else 0, "months": mn,
         "h1": round(sum(mn[m] for m in months[:5]), 2), "h2": round(sum(mn[m] for m in months[5:]), 2)}
    if not quiet:
        print("%-40s n=%5d net %+8.2f  m+ %2d/10  w+ %2d/%d  days %d/%d  wr %4.1f  [Jan-May %+.1f | Jun-Oct %+.1f]  %s" % (
            label, r["n"], r["net"], r["months_up"], r["weeks_up"], r["weeks"], r["days_traded"], r["days"], r["wr"], r["h1"], r["h2"],
            " ".join("%+.0f" % mn[m] for m in months)), flush=True)
    return r
