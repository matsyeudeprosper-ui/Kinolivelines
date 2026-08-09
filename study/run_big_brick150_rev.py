"""SPEC_BIG_BRICK_GATE addendum 4 - the fresh-reversal tweak.
Entry allowed only while the $150 series' LATEST brick is a reversal brick,
in its direction. Battery: A0 / F / rate-matched R, 6 anchors, M1/M5/M15 + H1.
"""
import numpy as np
import MetaTrader5 as mt5
from hedge_engine import simulate

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
R1 = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_M1, 0, 80000)
R5 = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_M5, 0, 80000)
R15 = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_M15, 0, 80000)
RH = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_H1, 0, 80000)
mt5.shutdown()

ANCH = range(6)
BRICK = 150.0


def big_rev_masks(R, brick=BRICK, rev=2):
    """buy/sell allowed at bar j only if the big series' most recent brick,
    as of bar j's close, is a REVERSAL brick - permission dies the moment a
    further big brick prints."""
    o = R["open"].astype(float)
    c = R["close"].astype(float)
    N = len(c)
    ao = ac = float(o[0])
    d = 0
    # A 2-brick reversal in this geometry ALWAYS prints two bricks atomically
    # (the flip + its paired continuation land at the same threshold), so
    # "latest brick is the reversal brick" would never be true. The reversal
    # EVENT is that pair: fresh while <=1 brick has printed since the flip.
    since = 99
    buy = np.zeros(N, bool)
    sell = np.zeros(N, bool)
    for j in range(N):
        ci = c[j]
        while True:
            up = (ao if d == -1 else ac) + brick * (rev if d == -1 else 1)
            dn = (ao if d == 1 else ac) - brick * (rev if d == 1 else 1)
            if ci >= up:
                base = ao if d == -1 else ac
                since = 0 if d == -1 else since + 1
                ao, ac, d = base, base + brick, 1
            elif ci <= dn:
                base = ao if d == 1 else ac
                since = 0 if d == 1 else since + 1
                ao, ac, d = base, base - brick, -1
            else:
                break
        if d != 0 and since <= 1:
            buy[j] = d == 1
            sell[j] = d == -1
    return buy, sell


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
for name, R in (("M1", R1), ("M5", R5), ("M15", R15), ("H1", RH)):
    months = (R["time"][-1] - R["time"][0]) / (86400 * 30.44)
    print(f"--- {name} ({months:.1f} months) ---")
    mb, ms = big_rev_masks(R)
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
    assert opF != op0, "gate inert"
    eqR = np.mean([eqv(run6(R, entry_filter=("random", share), filter_seed=s))
                   for s in (0, 1, 2)], axis=0)
    mA, sA, bA = stats(eqF, eq0)
    mR, sR, bR = stats(eqF, eqR)
    print(f"  Frev    mean {eqF.mean():9.2f}  dead {sum(r['dead'] for r in rsF)}/6  "
          f"cycles {opF:7.0f}  share {share:5.1%}")
    print(f"  vs A0 {mA:+9.2f}  2SE {sA:7.2f}  better {bA}/6")
    print(f"  vs R  {mR:+9.2f}  2SE {sR:7.2f}  better {bR}/6")
    res[name] = dict(mA=mA, sA=sA, bA=bA, mR=mR, sR=sR, bR=bR,
                     deadF=sum(r["dead"] for r in rsF))
    print()

print("=" * 90)
print("SUMMARY (fresh-reversal tweak)")
for tf, r in res.items():
    print(f"  {tf:<4} vs A0 {r['mA']:+9.2f} (2SE {r['sA']:7.2f}, {r['bA']}/6)   "
          f"vs R {r['mR']:+9.2f} (2SE {r['sR']:7.2f}, {r['bR']}/6)   dead {r['deadF']}/6")
