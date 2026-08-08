"""SPEC_COST_FILTERS - the two mechanism-backed negative filters, preregistered.

  W  - no NEW cycles on Saturday/Sunday UTC (measured weekend deficit,
       thin-liquidity mechanism, BTC and ETH both significant)
  A  - no NEW cycles when ATR14(own TF, Wilder, causal) < $50, i.e. when the
       fixed $10 spread exceeds ~20% of a bar's typical range (cost-share
       mechanism; threshold fixed by arithmetic, not tuned)
  WA - both

Open baskets are always managed; the filters gate cycle starts only, via the
engine's generic mask entry_filter (same mask for buy and sell - these are
direction-neutral timing rules, not predictions).

Bar: must beat rate-matched RANDOM skipping (3 seeds averaged), not just A0 -
the brake-family lesson: on dying configs anything that trades less looks
good. Windows: full sample AND each half, reported separately. No picking.
"""
import datetime as dt
import numpy as np
import MetaTrader5 as mt5
from hedge_engine import simulate

SPREAD = 10.0
ATR_MIN = 5 * SPREAD
ANCH = range(6)


def fetch(tf, want):
    n = want
    while n > 500:
        r = mt5.copy_rates_from_pos("BTCUSDm", tf, 0, n)
        if r is not None and len(r) > 0:
            return r
        n = int(n * 0.9)
    raise RuntimeError("no data")


mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
DATA = (("M1", fetch(mt5.TIMEFRAME_M1, 80000)),
        ("M5", fetch(mt5.TIMEFRAME_M5, 80000)),
        ("M15", fetch(mt5.TIMEFRAME_M15, 50000)))
mt5.shutdown()


def atr14(R):
    h = R["high"].astype(float)
    l = R["low"].astype(float)
    c = R["close"].astype(float)
    pc = np.concatenate([[c[0]], c[:-1]])
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    N = len(c)
    a = np.full(N, np.nan)
    if N > 14:
        a[13] = tr[:14].mean()
        for i in range(14, N):
            a[i] = (a[i - 1] * 13 + tr[i]) / 14.0
    return a


def masks(R):
    wd = np.array([dt.datetime.utcfromtimestamp(t).weekday() for t in R["time"]])
    w = wd < 5
    a_ = atr14(R)
    a = np.where(np.isnan(a_), True, a_ >= ATR_MIN)   # warm-up = A0 behaviour
    return {"W": w, "A": a, "WA": w & a}


def run6(Rh, **kw):
    rs = []
    for a in ANCH:
        r = simulate(Rh, a=a, arm="same", **kw)
        assert r["ok"], f"invariant failed anchor {a}"
        rs.append(r)
    return rs


def eqv(rs):
    return np.array([r["eq"] for r in rs])


def stats(eqA, eqB):
    d = eqA - eqB
    se2 = 2 * d.std(ddof=1) / np.sqrt(len(d))
    return float(d.mean()), float(se2), int((d > 0).sum())


for name, R in DATA:
    n = len(R)
    windows = (("full", R), ("half1", R[:n // 2]), ("half2", R[n // 2:]))
    print("=" * 100)
    print(f"### {name}")
    for wname, Rh in windows:
        months = (Rh["time"][-1] - Rh["time"][0]) / (86400 * 30.44)
        M = masks(Rh)
        rs0 = run6(Rh)
        eq0 = eqv(rs0)
        op0 = np.mean([r["opened"] for r in rs0])
        print(f"--- {name} {wname} ({months:.1f} mo) --- "
              f"A0 mean {eq0.mean():8.2f}  dead {sum(r['dead'] for r in rs0)}/6  cycles {op0:.0f}")
        for fname, m in M.items():
            mm = np.asarray(m, bool)
            rsF = run6(Rh, entry_filter=("mask", mm, mm))
            eqF = eqv(rsF)
            seen = sum(r["f_seen"] for r in rsF)
            passed = sum(r["f_pass"] for r in rsF)
            share = passed / seen if seen else float("nan")
            eqR = np.mean([eqv(run6(Rh, entry_filter=("random", share), filter_seed=s))
                           for s in (0, 1, 2)], axis=0)
            mA, sA, bA = stats(eqF, eq0)
            mR, sR, bR = stats(eqF, eqR)
            print(f"  {fname:<3} mean {eqF.mean():8.2f}  dead {sum(r['dead'] for r in rsF)}/6  "
                  f"share {share:5.1%}  vs A0 {mA:+8.2f} 2SE {sA:6.2f} ({bA}/6)  "
                  f"vs R {mR:+8.2f} 2SE {sR:6.2f} ({bR}/6)")
        print()
