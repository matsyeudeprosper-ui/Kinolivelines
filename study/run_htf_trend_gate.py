"""SPEC_HTF_TREND_GATE - one-shot, criteria preregistered in the spec.

New cycles only in the higher timeframe's trend direction (last CLOSED HTF
close vs EMA21). M1 gates on H1, M5 on H4, M15 on D1. arm="same", 6 anchors,
rate-matched random control seeds 0/1/2.
"""
import numpy as np
import MetaTrader5 as mt5
from hedge_engine import simulate

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
R1 = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_M1, 0, 80000)
R5 = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_M5, 0, 80000)
R15 = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_M15, 0, 80000)
H1 = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_H1, 0, 80000)
H4 = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_H4, 0, 50000)
D1 = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_D1, 0, 10000)
mt5.shutdown()

ANCH = range(6)


def ema21(x):
    a = 2.0 / (21 + 1)
    out = np.empty(len(x))
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out


def trend_masks(R, tf_e, H, tf_h):
    """buy[j]/sell[j] from the last HTF bar fully CLOSED when entry bar j
    closes: close > EMA21 -> buy only, < -> sell only."""
    hc = H["close"].astype(float)
    e = ema21(hc)
    h_close_t = H["time"].astype(np.int64) + tf_h
    j_close_t = R["time"].astype(np.int64) + tf_e
    idx = np.searchsorted(h_close_t, j_close_t, side="right") - 1
    buy = np.zeros(len(R), bool)
    sell = np.zeros(len(R), bool)
    ok = idx >= 21                     # EMA warm (idx 0-20 unreliable)
    up = np.zeros(len(R), bool)
    dn = np.zeros(len(R), bool)
    up[ok] = hc[idx[ok]] > e[idx[ok]]
    dn[ok] = hc[idx[ok]] < e[idx[ok]]
    buy[ok] = up[ok]
    sell[ok] = dn[ok]
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
for name, R, tf_e, H, tf_h in (("M1", R1, 60, H1, 3600),
                               ("M5", R5, 300, H4, 14400),
                               ("M15", R15, 900, D1, 86400)):
    months = (R["time"][-1] - R["time"][0]) / (86400 * 30.44)
    print(f"--- {name} ({months:.1f} months) gated on "
          f"{'H1' if tf_h==3600 else 'H4' if tf_h==14400 else 'D1'} EMA21 ---")
    mb, ms = trend_masks(R, tf_e, H, tf_h)
    rs0 = run6(R)
    eq0 = eqv(rs0)
    op0 = np.mean([r["opened"] for r in rs0])
    print(f"  A0        mean {eq0.mean():9.2f}  dead {sum(r['dead'] for r in rs0)}/6  cycles {op0:6.0f}")
    rsF = run6(R, entry_filter=("mask", mb, ms))
    eqF = eqv(rsF)
    seen = sum(r["f_seen"] for r in rsF)
    passed = sum(r["f_pass"] for r in rsF)
    share = passed / seen if seen else float("nan")
    opF = np.mean([r["opened"] for r in rsF])
    if opF == op0:
        print("*** GATE INERT - same cycles as A0, ABORT ***")
        raise SystemExit(1)
    eqR = np.mean([eqv(run6(R, entry_filter=("random", share), filter_seed=s))
                   for s in (0, 1, 2)], axis=0)
    mA, sA, bA = stats(eqF, eq0)
    mR, sR, bR = stats(eqF, eqR)
    print(f"  F trend   mean {eqF.mean():9.2f}  dead {sum(r['dead'] for r in rsF)}/6  "
          f"cycles {opF:6.0f}  share {share:5.1%}")
    print(f"  vs A0 {mA:+9.2f}  2SE {sA:7.2f}  better {bA}/6")
    print(f"  vs R  {mR:+9.2f}  2SE {sR:7.2f}  better {bR}/6")
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
print(f"  1. beats A0 on >=2 TFs (mean>2SE, >=5/6), no >2SE loss: "
      f"{n_a0 >= 2 and not big_a0}  ({n_a0}/3, big loss {big_a0})")
print(f"  2. beats R the same way: {n_r >= 2 and not big_r}  ({n_r}/3, big loss {big_r})")
print(f"  3. share 20-80% somewhere: {share_ok}")
print(f"  SURVIVES: {n_a0 >= 2 and not big_a0 and n_r >= 2 and not big_r and share_ok}")
