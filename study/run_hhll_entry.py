"""SPEC_HHLL_ENTRY - one-shot run, criteria preregistered in the spec.

Arms per timeframe, 6 anchors each, arm="same" (the live rule):
  A0  live rule
  F   HH/LL structure filter on new cycles (3 closed bars, lookback fixed)
  R   rate-matched random filter, p = F's measured accept share on that
      timeframe, seeds 0/1/2 averaged per anchor
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
        assert r["ok"], f"invariant failed {kw} anchor {a}"
        rs.append(r)
    return rs


def eqv(rs):
    return np.array([r["eq"] for r in rs])


def show(label, eq, dead, opened, eq0=None):
    extra = ""
    if eq0 is not None:
        d = eq - eq0
        se2 = 2 * d.std(ddof=1) / np.sqrt(len(d))
        extra = f"  vs A0 {d.mean():+9.2f}  2SE {se2:7.2f}  better {(d>0).sum()}/6"
    print(f"  {label:<14} mean {eq.mean():9.2f}  dead {dead}/6  cycles {opened:6.0f}{extra}")


def beats(eqA, eqB):
    """criterion shape from the spec: mean > 2SE and >=5/6 anchors"""
    d = eqA - eqB
    se2 = 2 * d.std(ddof=1) / np.sqrt(len(d))
    return d.mean() > se2 and (d > 0).sum() >= 5, float(d.mean()), float(se2)


def loses_big(eqA, eqB):
    d = eqA - eqB
    se2 = 2 * d.std(ddof=1) / np.sqrt(len(d))
    return d.mean() < -se2


res = {}
for name, R in (("M1", R1), ("M5", R5), ("M15", R15)):
    months = (R["time"][-1] - R["time"][0]) / (86400 * 30.44)
    print(f"--- {name} ({months:.1f} months, {len(R)} bars) ---")

    rs0 = run6(R)
    eq0 = eqv(rs0)
    show("A0", eq0, sum(r["dead"] for r in rs0), np.mean([r["opened"] for r in rs0]))

    rsF = run6(R, entry_filter=("hhll",))
    eqF = eqv(rsF)
    seen = sum(r["f_seen"] for r in rsF)
    passed = sum(r["f_pass"] for r in rsF)
    share = passed / seen if seen else float("nan")
    show("F hh/ll", eqF, sum(r["dead"] for r in rsF),
         np.mean([r["opened"] for r in rsF]), eq0)
    print(f"  accept share {share:.1%} ({passed}/{seen})")

    # dead-gate check: F must actually open fewer cycles than A0
    if np.mean([r["opened"] for r in rsF]) == np.mean([r["opened"] for r in rs0]):
        print("*** F OPENED THE SAME CYCLES AS A0 - DEAD GATE, ABORT ***")
        raise SystemExit(1)

    # R: rate-matched random, seeds 0/1/2 averaged per anchor
    eqR_seeds = []
    for s in (0, 1, 2):
        rsR = run6(R, entry_filter=("random", share), filter_seed=s)
        eqR_seeds.append(eqv(rsR))
    eqR = np.mean(eqR_seeds, axis=0)
    show("R random", eqR, 0, 0, eq0)

    fa, fam, fas = beats(eqF, eq0)
    fr, frm, frs = beats(eqF, eqR)
    res[name] = dict(share=share, eq0=eq0, eqF=eqF, eqR=eqR,
                     f_beats_a0=fa, f_a0=(fam, fas),
                     f_beats_r=fr, f_r=(frm, frs),
                     f_loses_a0=loses_big(eqF, eq0),
                     f_loses_r=loses_big(eqF, eqR))
    print()

print("=" * 90)
print("VERDICT (spec criteria, all required)")
share_ok = any(0.20 <= r["share"] <= 0.80 for r in res.values())
n_a0 = sum(r["f_beats_a0"] for r in res.values())
n_r = sum(r["f_beats_r"] for r in res.values())
big_loss_a0 = any(r["f_loses_a0"] for r in res.values())
big_loss_r = any(r["f_loses_r"] for r in res.values())
for tf, r in res.items():
    print(f"  {tf:<4} share {r['share']:5.1%}  "
          f"F-A0 {r['f_a0'][0]:+9.2f} (2SE {r['f_a0'][1]:7.2f}) beats:{r['f_beats_a0']}  "
          f"F-R {r['f_r'][0]:+9.2f} (2SE {r['f_r'][1]:7.2f}) beats:{r['f_beats_r']}")
print(f"  1. F beats A0 on >=2 timeframes, no >2SE loss on the third: "
      f"{n_a0 >= 2 and not big_loss_a0}  ({n_a0}/3 beaten, big loss: {big_loss_a0})")
print(f"  2. F beats R the same way: {n_r >= 2 and not big_loss_r}  "
      f"({n_r}/3 beaten, big loss: {big_loss_r})")
print(f"  3. accept share 20-80% somewhere: {share_ok}")
survives = n_a0 >= 2 and not big_loss_a0 and n_r >= 2 and not big_loss_r and share_ok
print(f"  SURVIVES: {survives}")
