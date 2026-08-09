"""SPEC_WIN_STOP - one-shot run, criteria preregistered in the spec.

W = stop the UTC day after the first winning cycle (win = cycle P&L > 0).
C = count-matched control: cap of N cycles/day, N = W's measured mean
    cycles/day on that timeframe (rounded, min 1).
"""
import numpy as np
import datetime as dt
import MetaTrader5 as mt5
from hedge_engine import simulate

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
R1 = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_M1, 0, 80000)
R5 = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_M5, 0, 80000)
R15 = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_M15, 0, 80000)
mt5.shutdown()

ANCH = range(6)


def run6(R, **kw):
    rs = []
    for a in ANCH:
        r = simulate(R, a=a, arm="same", **kw)
        assert r["ok"], f"invariant failed anchor {a}"
        rs.append(r)
    return rs


def eqv(rs):
    return np.array([r["eq"] for r in rs])


def stats(eqA, eqB):
    d = eqA - eqB
    se2 = 2 * d.std(ddof=1) / np.sqrt(len(d))
    return float(d.mean()), float(se2), int((d > 0).sum())


res = {}
for name, R in (("M1", R1), ("M5", R5), ("M15", R15)):
    months = (R["time"][-1] - R["time"][0]) / (86400 * 30.44)
    n_days = len(np.unique(np.asarray(R["time"], dtype=np.int64) // 86400))
    print(f"--- {name} ({months:.1f} months, {n_days} days) ---")
    rs0 = run6(R)
    eq0 = eqv(rs0)
    op0 = np.mean([r["opened"] for r in rs0])
    print(f"  A0      mean {eq0.mean():9.2f}  dead {sum(r['dead'] for r in rs0)}/6  cycles {op0:7.0f}")
    rsW = run6(R, day_stop="win")
    eqW = eqv(rsW)
    opW = np.mean([r["opened"] for r in rsW])
    N = max(1, round(opW / n_days))
    rsC = run6(R, day_stop=("cap", N))
    eqC = eqv(rsC)
    opC = np.mean([r["opened"] for r in rsC])
    mA, sA, bA = stats(eqW, eq0)
    mC, sC, bC = stats(eqW, eqC)
    print(f"  W       mean {eqW.mean():9.2f}  dead {sum(r['dead'] for r in rsW)}/6  cycles {opW:7.0f}  ({opW/n_days:.1f}/day)")
    print(f"  C cap{N} mean {eqC.mean():9.2f}  dead {sum(r['dead'] for r in rsC)}/6  cycles {opC:7.0f}")
    print(f"  W vs A0 {mA:+9.2f}  2SE {sA:7.2f}  better {bA}/6")
    print(f"  W vs C  {mC:+9.2f}  2SE {sC:7.2f}  better {bC}/6")
    res[name] = dict(beats_a0=(mA > sA and bA >= 5), loses_a0=(mA < -sA),
                     beats_c=(mC > sC and bC >= 5), loses_c=(mC < -sC),
                     reduced=(opW < op0), thin=(opW < 0.2 * op0))
    print()

print("=" * 90)
print("VERDICT (spec criteria, all required)")
n_a0 = sum(r["beats_a0"] for r in res.values())
n_c = sum(r["beats_c"] for r in res.values())
big_a0 = any(r["loses_a0"] for r in res.values())
big_c = any(r["loses_c"] for r in res.values())
reduced = all(r["reduced"] for r in res.values())
thin = any(r["thin"] for r in res.values())
print(f"  1. W beats A0 on >=2 TFs (mean>2SE, >=5/6), no >2SE loss: "
      f"{n_a0 >= 2 and not big_a0}  ({n_a0}/3, big loss {big_a0})")
print(f"  2. W beats C the same way: {n_c >= 2 and not big_c}  ({n_c}/3, big loss {big_c})")
print(f"  3. gate fires everywhere, nowhere below 20% of A0: {reduced and not thin}")
print(f"  SURVIVES: {n_a0 >= 2 and not big_a0 and n_c >= 2 and not big_c and reduced and not thin}")
