"""ma2_months_test.py - the owner's two-chart rule (ma-methode-2-graphiques) on other months, fast (2026-11-07).

Rule (as built in robots.json, piece p-bougie-contre-min<N>): the pullback chart's last finished candle is bearish (bullish),
this 1-minute candle is shown on the silence chart and is green (red), it is the 1st or 2nd such candle since the pullback
candle finished, and the stop (the extreme of the pullback candle / this candle) is at least MIN points away. Target 1:1,
then 1:2 after a loss, back to 1:1 after a win. One trade at a time, entry at the candle's close, a buy pays the spread at
entry and a sell at its exit, stop first when both are touched in one minute. Money at 0.01 lot (1 point = 0.01 $).
This is the M1 bench, not the tick bench: it is checked against the tick bench on the robot's own 41 days first.
    python ma2_months_test.py <npz with bars + pb columns> [MIN ...]
"""
import sys, time
import numpy as np


def quiet(o, h, l, c):
    k = np.zeros(len(c), bool)
    rh = rl = None
    for i in range(len(c)):
        if rh is None or c[i] > rh or c[i] < rl:
            k[i] = True
            rh, rl = h[i], l[i]
    return k


def counts(po, pc, col):
    new = np.ones(len(po), bool)
    new[1:] = (po[1:] != po[:-1]) | (pc[1:] != pc[:-1])
    seg = np.cumsum(new)
    cs = np.cumsum(col.astype(float))
    base = np.concatenate([[0.0], cs])[np.nonzero(new)[0]]
    return cs - base[seg - 1]


def run(D, minr, target_rule="1r2r"):
    t, o, h, l, c, sp = (np.asarray(D[k], float) for k in ("time", "open", "high", "low", "close", "spread"))
    pdir, po, pc, ph, pl = (np.asarray(D[k], float) for k in ("pb_dir", "pb_open", "pb_close", "pb_high", "pb_low"))
    q = quiet(o, h, l, c)
    nu = counts(po, pc, q & (c >= o))
    nd = counts(po, pc, q & (c < o))
    T = []
    i, n, lost = 0, len(c), False
    while i < n - 1:
        side = 0
        if pdir[i] == -1 and q[i] and c[i] >= o[i] and nu[i] <= 2:
            side, sl = 1, min(pl[i], l[i])
        elif pdir[i] == 1 and q[i] and c[i] < o[i] and nd[i] <= 2:
            side, sl = -1, max(ph[i], h[i])
        if not side or np.isnan(sl):
            i += 1
            continue
        risk = (c[i] - sl) * side
        if risk < minr:
            i += 1
            continue
        e = c[i] + (sp[i] if side == 1 else 0.0)
        rr = (2.0 if lost else 1.0) if target_rule == "1r2r" else 2.0
        tp = e + side * rr * (e - sl) * side * side if side == 1 else e - rr * (sl - e)
        j = i + 1
        res = None
        while j < n:
            if side == 1:
                if l[j] <= sl: res = sl; break
                if h[j] >= tp: res = tp; break
            else:
                if h[j] + sp[j] >= sl: res = sl; break
                if l[j] + sp[j] <= tp: res = tp; break
            j += 1
        if res is None:
            break
        pnl = (res - e) * side * 0.01
        T.append((t[i], t[j], pnl))
        lost = pnl < 0
        i = j + 1
    return T


def summary(T):
    if not T:
        return {"trades": 0, "net": 0}
    p = np.array([x[2] for x in T])
    M = {}
    for ti, tj, pn in T:
        k = time.strftime("%Y-%m", time.gmtime(tj))
        M[k] = round(M.get(k, 0.0) + pn, 2)
    return {"trades": len(T), "net": round(float(p.sum()), 2), "win": round(float((p > 0).mean() * 100), 1), "months": M}


if __name__ == "__main__":
    D = np.load(sys.argv[1])
    for m in (sys.argv[2:] or ["200"]):
        print("min %s:" % m, summary(run(D, float(m))))
