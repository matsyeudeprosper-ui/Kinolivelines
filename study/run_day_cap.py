"""SPEC_DAY_CAP - one-shot run, criteria preregistered in the spec.

C2 = at most 2 new cycles per UTC day (fixed, no tuning).
R  = rate-matched random skip, p = C2/A0 cycle ratio, seeds 0/1/2.
"""
import numpy as np
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
    print(f"--- {name} ({months:.1f} months) ---")
    rs0 = run6(R)
    eq0 = eqv(rs0)
    op0 = np.mean([r["opened"] for r in rs0])
    print(f"  A0      mean {eq0.mean():9.2f}  dead {sum(r['dead'] for r in rs0)}/6  cycles {op0:7.0f}")
    rsC = run6(R, day_stop=("cap", 2))
    eqC = eqv(rsC)
    opC = np.mean([r["opened"] for r in rsC])
    p = opC / op0
    eqR = np.mean([eqv(run6(R, entry_filter=("random", p), filter_seed=s))
                   for s in (0, 1, 2)], axis=0)
    mA, sA, bA = stats(eqC, eq0)
    mR, sR, bR = stats(eqC, eqR)
    print(f"  C2      mean {eqC.mean():9.2f}  dead {sum(r['dead'] for r in rsC)}/6  cycles {opC:7.0f}  (keep {p:.1%})")
    print(f"  C2 vs A0 {mA:+9.2f}  2SE {sA:7.2f}  better {bA}/6")
    print(f"  C2 vs R  {mR:+9.2f}  2SE {sR:7.2f}  better {bR}/6")
    res[name] = dict(beats_a0=(mA > sA and bA >= 5), loses_a0=(mA < -sA),
                     beats_r=(mR > sR and bR >= 5), loses_r=(mR < -sR),
                     thin=(opC < 0.2 * op0))
    print()

print("=" * 90)
print("VERDICT (spec criteria, all required)")
n_a0 = sum(r["beats_a0"] for r in res.values())
n_r = sum(r["beats_r"] for r in res.values())
big_a0 = any(r["loses_a0"] for r in res.values())
big_r = any(r["loses_r"] for r in res.values())
thin = any(r["thin"] for r in res.values())
print(f"  1. C2 beats A0 on >=2 TFs (mean>2SE, >=5/6), no >2SE loss: "
      f"{n_a0 >= 2 and not big_a0}  ({n_a0}/3, big loss {big_a0})")
print(f"  2. C2 beats R the same way: {n_r >= 2 and not big_r}  ({n_r}/3, big loss {big_r})")
print(f"  3. keeps >=20% of A0 cycles everywhere: {not thin}")
print(f"  SURVIVES: {n_a0 >= 2 and not big_a0 and n_r >= 2 and not big_r and not thin}")
