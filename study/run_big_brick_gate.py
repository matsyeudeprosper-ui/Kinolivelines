"""SPEC_BIG_BRICK_GATE - one-shot run, criteria preregistered in the spec.

F = new 50-brick cycles only in the direction of the $100-brick series'
current brick at the signal bar's close. Big series mirrors the bots' exact
brick loop on the same closed bars - no lookahead.
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


def big_dir_masks(R, brick=100.0, rev=2):
    """direction of the big-brick series at each bar's close - the exact
    brick loop the bots and engine use, brick size doubled."""
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
    return dirs == 1, dirs == -1          # buy-allowed, sell-allowed


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
    mb, ms = big_dir_masks(R)
    rs0 = run6(R)
    eq0 = eqv(rs0)
    op0 = np.mean([r["opened"] for r in rs0])
    print(f"  A0      mean {eq0.mean():9.2f}  dead {sum(r['dead'] for r in rs0)}/6  cycles {op0:7.0f}")
    rsF = run6(R, entry_filter=("mask", mb, ms))
    eqF = eqv(rsF)
    seen = sum(r["f_seen"] for r in rsF)
    passed = sum(r["f_pass"] for r in rsF)
    share = passed / seen if seen else float("nan")
    opF = np.mean([r["opened"] for r in rsF])
    if opF == op0:
        print("*** GATE INERT - ABORT ***")
        raise SystemExit(1)
    eqR = np.mean([eqv(run6(R, entry_filter=("random", share), filter_seed=s))
                   for s in (0, 1, 2)], axis=0)
    mA, sA, bA = stats(eqF, eq0)
    mR, sR, bR = stats(eqF, eqR)
    print(f"  F big   mean {eqF.mean():9.2f}  dead {sum(r['dead'] for r in rsF)}/6  "
          f"cycles {opF:7.0f}  share {share:5.1%}")
    print(f"  F vs A0 {mA:+9.2f}  2SE {sA:7.2f}  better {bA}/6")
    print(f"  F vs R  {mR:+9.2f}  2SE {sR:7.2f}  better {bR}/6")
    res[name] = dict(share=share,
                     beats_a0=(mA > sA and bA >= 5), loses_a0=(mA < -sA),
                     beats_r=(mR > sR and bR >= 5), loses_r=(mR < -sR))
    print()

print("=" * 90)
print("VERDICT (spec criteria, all required)")
n_a0 = sum(r["beats_a0"] for r in res.values())
n_r = sum(r["beats_r"] for r in res.values())
big_a0 = any(r["loses_a0"] for r in res.values())
big_r = any(r["loses_r"] for r in res.values())
share_ok = any(0.20 <= r["share"] <= 0.80 for r in res.values())
print(f"  1. F beats A0 on >=2 TFs (mean>2SE, >=5/6), no >2SE loss: "
      f"{n_a0 >= 2 and not big_a0}  ({n_a0}/3, big loss {big_a0})")
print(f"  2. F beats R the same way: {n_r >= 2 and not big_r}  ({n_r}/3, big loss {big_r})")
print(f"  3. share 20-80% somewhere: {share_ok}")
print(f"  SURVIVES: {n_a0 >= 2 and not big_a0 and n_r >= 2 and not big_r and share_ok}")
