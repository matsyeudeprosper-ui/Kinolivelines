"""Redo with realistic short windows - the 500h version was dominated by
BTC's multi-year drift, not the trade's actual scale (TP=5 bricks, held
hours not weeks per HARVEST_SPEC)."""
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime

PCT, SPCT = 50.0 / 64000.0, 10.0 / 64000.0
REV, PT = 2, 0.01
FROM = datetime(2022, 1, 1)

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
r = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_H1, 0, 80000)
mt5.shutdown()
keep = r["time"] >= FROM.timestamp()
r = r[keep]
o, h, l, c = (r[k].astype(float) for k in ("open", "high", "low", "close"))
N = len(c)


def signals_pullback_retest():
    sigs = {}; ao = ac = float(o[0]); d = 0
    last_high = None; last_low = None
    for i in range(N):
        B = c[i] * PCT
        while True:
            up = (ao if d == -1 else ac) + B * (REV if d == -1 else 1)
            dn = (ao if d == 1 else ac) - B * (REV if d == 1 else 1)
            if c[i] >= up:
                if d == -1:
                    last_low = ac
                base = ao if d == -1 else ac; ao, ac, d = base, base + B, 1
            elif c[i] <= dn:
                if d == 1:
                    last_high = ac
                base = ao if d == 1 else ac; ao, ac, d = base, base - B, -1
            else:
                break
        if last_high is not None and h[i] >= last_high:
            sigs.setdefault(i, 1); last_high = None
        if last_low is not None and l[i] <= last_low:
            sigs.setdefault(i, -1); last_low = None
    return sigs


sigs = signals_pullback_retest()

for WINDOW in (6, 24, 48, 72, 168):
    mfe_pts = []; mfe_usd = []; censored = 0; brick_pts = []
    for j, dirn in sigs.items():
        if j + 1 >= N:
            continue
        ent_bar = j + 1
        SP = c[j] * SPCT
        L = (dirn == 1)
        entry = o[ent_bar] + SP if L else o[ent_bar]
        best = 0.0
        end = min(N, ent_bar + WINDOW)
        for k in range(ent_bar, end):
            best = max(best, (h[k] - entry) if L else (entry - l[k]))
        if end == ent_bar + WINDOW:
            censored += 1
        mfe_pts.append(best); mfe_usd.append(best * PT); brick_pts.append(c[j] * PCT)
    mfe_pts = np.array(mfe_pts); mfe_usd = np.array(mfe_usd); brick_pts = np.array(brick_pts)
    tp_target = 5 * brick_pts
    print(f"--- window {WINDOW}h ---  n={len(mfe_pts)}  censored(never gave up before window end) {100*censored/len(mfe_pts):.0f}%")
    print(f"  MFE mean {mfe_pts.mean():7.1f}pts (${mfe_pts.mean()*PT:6.2f})   median {np.median(mfe_pts):7.1f}pts (${np.median(mfe_pts)*PT:6.2f})")
    print(f"  reached own 5-brick TP: {100*np.mean(mfe_pts>=tp_target):5.1f}%   reached >=10 bricks: {100*np.mean(mfe_pts>=10*brick_pts):5.1f}%")
