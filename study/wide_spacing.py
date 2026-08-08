"""SPEC_WIDE_SPACING - selection on M15 first half, validation untouched.

Grid and criteria are in the spec, declared before this file existed. One D is
picked on the first half; if it fails the untouched data the spec CLOSES - no
second pick.
"""
import numpy as np
import MetaTrader5 as mt5
from hedge_engine import simulate

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
R1 = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_M1, 0, 80000)
R5 = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_M5, 0, 80000)
R15 = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_M15, 0, 80000)
mt5.shutdown()

GRID = (250.0, 500.0, 1000.0, 2000.0, 4000.0)
ANCH = range(6)
half = len(R15) // 2
R15a, R15b = R15[:half], R15[half:]


def run6(R, **kw):
    rs = []
    for a in ANCH:
        r = simulate(R, a=a, arm="same", **kw)
        assert r["ok"], f"invariant failed {kw} anchor {a}"
        rs.append(r)
    return rs


def summ(rs):
    eq = np.array([r["eq"] for r in rs])
    return eq, sum(1 for r in rs if r["dead"]), np.mean([r["hedges"] for r in rs])


def show(label, rs, eq0=None):
    eq, dead, adds = summ(rs)
    extra = ""
    if eq0 is not None:
        d = eq - eq0
        se2 = 2 * d.std(ddof=1) / np.sqrt(len(d))
        extra = f"  vs A0 {d.mean():+9.2f}  2SE {se2:7.2f}  better {(d>0).sum()}/6"
    print(f"  {label:<18} mean {eq.mean():9.2f}  dead {dead}/6  adds {adds:7.0f}{extra}")
    return eq


print("=" * 90)
print(f"SELECTION - M15 first half ({half} bars, "
      f"{(R15a['time'][-1]-R15a['time'][0])/86400/30.44:.1f} months), 6 anchors")
print("=" * 90)
rs0a = run6(R15a)
eq0a = show("A0", rs0a)

picked, best_mean = None, -1e18
sel = {}
for D in GRID:
    rs = run6(R15a, adapt={"add_dist": (0.0, D, D)})
    eq, dead, adds = summ(rs)
    show(f"D={D:.0f}", rs, eq0a)
    sel[D] = (eq.mean(), dead, adds)
    if dead <= 1 and eq.mean() > best_mean:          # survive >=5/6
        best_mean, picked = eq.mean(), D
# ties -> smaller D: iterate grid ascending and keep first equal-best
for D in GRID:
    if sel[D][1] <= 1 and abs(sel[D][0] - best_mean) < 1e-9:
        picked = D
        break

# Trap-16: distance arms must differ in add count
counts = [sel[D][2] for D in GRID]
if len(set(round(c) for c in counts)) == 1:
    print("*** ALL D ARMS HAVE IDENTICAL ADD COUNTS - DEAD GATE, ABORT ***")
    raise SystemExit(1)

print(f"\nSELECTED: D={picked} (mean {best_mean:.2f}); grid and rule preregistered.")
if picked is None:
    print("NO D SURVIVED SELECTION (>=5/6). SPEC CLOSES.")
    raise SystemExit(0)

print()
print("=" * 90)
print("VALIDATION - untouched data. One shot.")
print("=" * 90)
for name, R in (("M15 second half", R15b), ("M1 full", R1), ("M5 full", R5)):
    months = (R["time"][-1] - R["time"][0]) / (86400 * 30.44)
    print(f"--- {name} ({months:.1f} months) ---")
    rs0 = run6(R)
    eq0 = show("A0", rs0)
    eqD = show(f"D={picked:.0f}", run6(R, adapt={"add_dist": (0.0, picked, picked)}), eq0)
    eqC0 = show("C0 no adds", run6(R, max_basket=0), eq0)
    eqC2 = show("C2 cap 2", run6(R, max_basket=2), eq0)
    if name.startswith("M15"):
        d = eqD - eq0
        se2 = 2 * d.std(ddof=1) / np.sqrt(6)
        dead0 = sum(1 for r in rs0 if r["dead"])
        deadD = sum(1 for r in run6(R, adapt={"add_dist": (0.0, picked, picked)}) if r["dead"])
        c1 = (d > 0).sum() >= 5 and d.mean() > se2
        c2 = ((eqD - eqC0) > 0).sum() >= 4 and ((eqD - eqC2) > 0).sum() >= 4
        c4 = deadD < dead0
        v15 = dict(c1=c1, c2=c2, c4=c4, mean=float(d.mean()), se2=float(se2),
                   beat0=int(((eqD - eqC0) > 0).sum()),
                   beat2=int(((eqD - eqC2) > 0).sum()))
    elif name.startswith("M1 "):
        d1m = float((eqD - eq0).mean()); d1s = float(2 * (eqD - eq0).std(ddof=1) / np.sqrt(6))
    else:
        d5m = float((eqD - eq0).mean()); d5s = float(2 * (eqD - eq0).std(ddof=1) / np.sqrt(6))

print()
print("=" * 90)
print("VERDICT (spec section 4)")
c3 = not (d1m < -d1s) and not (d5m < -d5s)
print(f"  1. beats A0 on M15-h2 >=5/6, mean>2SE : {v15['c1']}  "
      f"(mean {v15['mean']:+.2f}, 2SE {v15['se2']:.2f})")
print(f"  2. beats BOTH cap controls >=4/6      : {v15['c2']}  "
      f"(vs C0 {v15['beat0']}/6, vs C2 {v15['beat2']}/6)")
print(f"  3. no M1/M5 loss beyond 2SE           : {c3}  "
      f"(M1 {d1m:+.2f}/{d1s:.2f}, M5 {d5m:+.2f}/{d5s:.2f})")
print(f"  4. fewer wipeouts than A0 on M15-h2   : {v15['c4']}")
print(f"  SURVIVES: {v15['c1'] and v15['c2'] and c3 and v15['c4']}")
