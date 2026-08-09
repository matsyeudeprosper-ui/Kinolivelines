"""SPEC_FRESH_EARLY_COMBO addendum - the ETH out-of-sample confirmation.
Same fixed rule, bricks scaled to ETH's price level (same proportion as
$50 on ~65k BTC), spread measured from live quotes.
"""
import numpy as np
import MetaTrader5 as mt5
from hedge_engine import simulate

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
tick = mt5.symbol_info_tick("ETHUSDm")
DATA = [("M1", mt5.copy_rates_from_pos("ETHUSDm", mt5.TIMEFRAME_M1, 0, 80000)),
        ("M5", mt5.copy_rates_from_pos("ETHUSDm", mt5.TIMEFRAME_M5, 0, 80000)),
        ("M15", mt5.copy_rates_from_pos("ETHUSDm", mt5.TIMEFRAME_M15, 0, 80000)),
        ("H1", mt5.copy_rates_from_pos("ETHUSDm", mt5.TIMEFRAME_H1, 0, 80000))]
mt5.shutdown()

SPREAD = round(tick.ask - tick.bid, 2)
px0 = float(DATA[0][1]["close"][-1])
# same proportions as BTC: 50/65000 and 150/65000 of price, rounded cleanly
BRICK_S = round(px0 * 50.0 / 65000.0, 1)
BRICK_B = round(px0 * 150.0 / 65000.0, 1)
print(f"ETHUSDm  price ~{px0:.0f}  spread {SPREAD}  "
      f"brick {BRICK_S}  big brick {BRICK_B}")
print(f"sanity: spread/brick = {SPREAD/BRICK_S:.2f} (BTC is 10/50 = 0.20)")
print()

ANCH = range(6)


def fresh_rev_masks(R, brick, rev=2):
    o = R["open"].astype(float)
    c = R["close"].astype(float)
    N = len(c)
    ao = ac = float(o[0])
    d = 0
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
        r = simulate(R, a=a, arm="same", spread=SPREAD, brick=BRICK_S, **kw)
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
for name, R in DATA:
    months = (R["time"][-1] - R["time"][0]) / (86400 * 30.44)
    print(f"--- ETH {name} ({months:.1f} months) ---")
    mb, ms = fresh_rev_masks(R, BRICK_B)
    rs0 = run6(R)
    eq0 = eqv(rs0)
    op0 = np.mean([r["opened"] for r in rs0])
    rsX = run6(R, entry_filter=("mask", mb, ms), day_stop=("cap", 2))
    eqX = eqv(rsX)
    opX = np.mean([r["opened"] for r in rsX])
    assert opX != op0, "gate inert"
    p = opX / op0
    eqR = np.mean([eqv(run6(R, entry_filter=("random", p), filter_seed=s))
                   for s in (0, 1, 2)], axis=0)
    mR, sR, bR = stats(eqX, eqR)
    mA, sA, bA = stats(eqX, eq0)
    print(f"  A0     mean {eq0.mean():9.2f}  dead {sum(r['dead'] for r in rs0)}/6  cycles {op0:7.0f}")
    print(f"  COMBO  mean {eqX.mean():9.2f}  dead {sum(r['dead'] for r in rsX)}/6  "
          f"cycles {opX:7.0f}  (keep {p:.1%})")
    print(f"  vs A0 {mA:+9.2f}  2SE {sA:7.2f}  better {bA}/6")
    print(f"  vs R  {mR:+9.2f}  2SE {sR:7.2f}  better {bR}/6")
    res[name] = dict(mean=float(eqX.mean()), deadX=sum(r["dead"] for r in rsX),
                     beats_r=(mR > sR and bR >= 5), loses_r=(mR < -sR))
    print()

print("=" * 90)
print("VERDICT (ETH confirmation criteria)")
no_dead = all(r["deadX"] == 0 for r in res.values())
n_r = sum(r["beats_r"] for r in res.values())
big_r = any(r["loses_r"] for r in res.values())
print(f"  1. zero wipeouts everywhere: {no_dead}")
print(f"  2. beats R (mean>2SE, >=5/6) on >=1 of 4, no >2SE loss to R: "
      f"{n_r >= 1 and not big_r}  ({n_r}/4, big loss {big_r})")
print(f"  CONFIRMS: {no_dead and n_r >= 1 and not big_r}")
