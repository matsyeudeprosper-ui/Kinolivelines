"""SPEC_FRESH_EARLY_COMBO - ETH re-validation on the DEMO Pro feed
(ETHUSD, Exness-MT5Trial9) before adding it as a second forward
stream, 2026-09-08. Bricks scaled to ETH price (same proportion as
$50 on ~65k BTC); spread measured live; cap 3 (the deployed config)
checked alongside the original cap 4.
"""
import json
import os
import numpy as np
import MetaTrader5 as mt5
from hedge_engine import simulate

_SECRETS = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "..", "live", "owl_secrets.json")  # not in git
mt5.initialize(path=r"C:\NestTerminals\u476954287\terminal64.exe",
               login=476954287,
               password=json.load(open(_SECRETS, encoding="utf-8"))["mt5_password"],
               server="Exness-MT5Trial9", timeout=90000)
mt5.symbol_select("ETHUSD", True)
import time
time.sleep(2)
tick = mt5.symbol_info_tick("ETHUSD")
R = mt5.copy_rates_from_pos("ETHUSD", mt5.TIMEFRAME_H1, 0, 80000)
mt5.shutdown()

SPREAD = round(tick.ask - tick.bid, 2)
px0 = float(R["close"][-1])
BRICK_S = round(px0 * 50.0 / 65000.0, 1)
BRICK_B = round(px0 * 150.0 / 65000.0, 1)
months = (R["time"][-1] - R["time"][0]) / (86400 * 30.44)
print(f"ETHUSD price ~{px0:.0f} spread {SPREAD} brick {BRICK_S} "
      f"big {BRICK_B} | spread/brick {SPREAD/BRICK_S:.2f} "
      f"(BTC pro = 7/50 = 0.14) | H1 {months:.1f} months", flush=True)

o = R["open"].astype(float)
c = R["close"].astype(float)
N = len(c)
ao = ac = float(o[0]); d = 0; since = 99
mb = np.zeros(N, bool); ms = np.zeros(N, bool)
for j in range(N):
    ci = c[j]
    while True:
        up = (ao if d == -1 else ac) + BRICK_B * (2 if d == -1 else 1)
        dn = (ao if d == 1 else ac) - BRICK_B * (2 if d == 1 else 1)
        if ci >= up:
            base = ao if d == -1 else ac
            since = 0 if d == -1 else since + 1
            ao, ac, d = base, base + BRICK_B, 1
        elif ci <= dn:
            base = ao if d == 1 else ac
            since = 0 if d == 1 else since + 1
            ao, ac, d = base, base - BRICK_B, -1
        else:
            break
    if d != 0 and since <= 1:
        mb[j] = d == 1
        ms[j] = d == -1


def run6(**kw):
    rs = []
    for a in range(6):
        r = simulate(R, a=a, arm="same", spread=SPREAD, brick=BRICK_S,
                     **kw)
        assert r["ok"], f"invariant failed anchor {a}"
        rs.append(r)
    return rs


base_op = np.mean([r["opened"] for r in run6()])
for cap in (4, 3):
    rs = run6(entry_filter=("mask", mb, ms), day_stop=("cap", 2),
              max_basket=cap)
    eq = np.array([r["eq"] for r in rs])
    op = np.mean([r["opened"] for r in rs])
    dd = max(r["mdd"] for r in rs)
    wc = min((min(r["cycles"]) if r["cycles"] else 0.0) for r in rs)
    dead = sum(r["dead"] for r in rs)
    p = op / base_op
    eqR = np.mean([np.array([r["eq"] for r in
                   run6(entry_filter=("random", p), filter_seed=s,
                        max_basket=cap)])
                   for s in (0, 1, 2)], axis=0)
    dv = eq - eqR
    se2 = 2 * dv.std(ddof=1) / np.sqrt(len(dv))
    print(f"cap {cap}: eq {eq.mean():+8.2f} dead {dead}/6 "
          f"maxDD {dd:7.2f} worstCycle {wc:+8.2f} cycles {op:5.0f} "
          f"vsR {dv.mean():+8.2f} 2SE {se2:6.2f} "
          f"better {(dv > 0).sum()}/6", flush=True)
