"""H1 fresh+early combo: basket cap sweep (4 vs 3 vs 2 vs 1) on Pro
BTCUSD $7. The cap sets the LOSS UNIT (worst cycle ~ cap x $50); at
0.01 lots on a $200 account cap-4 (worst -199, maxDD 343) does not
fit. Question: does the edge survive a smaller cap?
Note: 'cap-2 alone dies on H1' in the memory was cap-2 WITHOUT the
fresh gate - the combo x cap cell is measured here for the first
time. Random control at matched rate for each cap.
"""
import numpy as np
import MetaTrader5 as mt5
from hedge_engine import simulate

mt5.initialize(path=r"C:\NestTerminals\u223985697\terminal64.exe")
R = mt5.copy_rates_from_pos("BTCUSD", mt5.TIMEFRAME_H1, 0, 80000)
mt5.shutdown()

o = R["open"].astype(float)
c = R["close"].astype(float)
N = len(c)
ao = ac = float(o[0]); d = 0; since = 99
mb = np.zeros(N, bool); ms = np.zeros(N, bool)
for j in range(N):
    ci = c[j]
    while True:
        up = (ao if d == -1 else ac) + 150.0 * (2 if d == -1 else 1)
        dn = (ao if d == 1 else ac) - 150.0 * (2 if d == 1 else 1)
        if ci >= up:
            base = ao if d == -1 else ac
            since = 0 if d == -1 else since + 1
            ao, ac, d = base, base + 150.0, 1
        elif ci <= dn:
            base = ao if d == 1 else ac
            since = 0 if d == 1 else since + 1
            ao, ac, d = base, base - 150.0, -1
        else:
            break
    if d != 0 and since <= 1:
        mb[j] = d == 1
        ms[j] = d == -1


def run6(**kw):
    rs = []
    for a in range(6):
        r = simulate(R, a=a, arm="same", spread=7.0, **kw)
        assert r["ok"], f"invariant failed anchor {a}"
        rs.append(r)
    return rs


base_op = np.mean([r["opened"] for r in run6()])
for cap in (4, 3, 2, 1):
    rs = run6(entry_filter=("mask", mb, ms), day_stop=("cap", 2),
              max_basket=cap)
    eq = np.array([r["eq"] for r in rs])
    op = np.mean([r["opened"] for r in rs])
    dd = max(r["mdd"] for r in rs)
    wc = min(min(r["cycles"]) for r in rs)
    dead = sum(r["dead"] for r in rs)
    p = op / base_op
    eqR = np.mean([np.array([r["eq"] for r in
                   run6(entry_filter=("random", p), filter_seed=s,
                        max_basket=cap)])
                   for s in (0, 1, 2)], axis=0)
    dv = eq - eqR
    se2 = 2 * dv.std(ddof=1) / np.sqrt(len(dv))
    print(f"cap {cap}: eq {eq.mean():+8.2f} dead {dead}/6 "
          f"maxDD {dd:7.2f} worstCycle {wc:+8.2f} "
          f"vsR {dv.mean():+8.2f} 2SE {se2:6.2f} "
          f"better {(dv > 0).sum()}/6", flush=True)
