"""SPEC_BIG_BRICK_GATE addendum - the preregistered H1 out-of-sample check.
Same fixed rule, data no brick-gate hypothesis has touched."""
import numpy as np
import MetaTrader5 as mt5
from hedge_engine import simulate
# NOT imported from run_big_brick_gate - that module runs its whole test at
# import (trap 8 family). Copied verbatim instead.


def big_dir_masks(R, brick=100.0, rev=2):
    o = R["open"].astype(float)
    c = R["close"].astype(float)
    N = len(c)
    ao = ac = float(o[0])
    d = 0
    dirs = np.zeros(N, dtype=np.int8)
    for j in range(N):
        ci = c[j]
        while True:
            up = (ao if d == -1 else ac) + brick * (rev if d == -1 else 1)
            dn = (ao if d == 1 else ac) - brick * (rev if d == 1 else 1)
            if ci >= up:
                base = ao if d == -1 else ac
                ao, ac, d = base, base + brick, 1
            elif ci <= dn:
                base = ao if d == 1 else ac
                ao, ac, d = base, base - brick, -1
            else:
                break
        dirs[j] = d
    return dirs == 1, dirs == -1

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
RH = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_H1, 0, 80000)
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


months = (RH["time"][-1] - RH["time"][0]) / (86400 * 30.44)
print(f"--- H1 out-of-sample ({months:.1f} months, {len(RH)} bars) ---")
mb, ms = big_dir_masks(RH)
rs0 = run6(RH)
eq0 = eqv(rs0)
op0 = np.mean([r["opened"] for r in rs0])
print(f"  A0      mean {eq0.mean():9.2f}  dead {sum(r['dead'] for r in rs0)}/6  cycles {op0:7.0f}")
rsF = run6(RH, entry_filter=("mask", mb, ms))
eqF = eqv(rsF)
seen = sum(r["f_seen"] for r in rsF)
passed = sum(r["f_pass"] for r in rsF)
share = passed / seen if seen else float("nan")
opF = np.mean([r["opened"] for r in rsF])
assert opF != op0, "gate inert"
eqR = np.mean([eqv(run6(RH, entry_filter=("random", share), filter_seed=s))
               for s in (0, 1, 2)], axis=0)
mA, sA, bA = stats(eqF, eq0)
mR, sR, bR = stats(eqF, eqR)
print(f"  F big   mean {eqF.mean():9.2f}  dead {sum(r['dead'] for r in rsF)}/6  "
      f"cycles {opF:7.0f}  share {share:5.1%}")
print(f"  F vs A0 {mA:+9.2f}  2SE {sA:7.2f}  better {bA}/6")
print(f"  F vs R  {mR:+9.2f}  2SE {sR:7.2f}  better {bR}/6")
print()
ok = (mA > sA and bA >= 5) and (mR > sR and bR >= 5)
print(f"SURVIVES H1 OUT-OF-SAMPLE (beats A0 AND R, mean>2SE, >=5/6): {ok}")
