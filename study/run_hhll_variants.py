"""SPEC_HHLL_VARIANTS - selection on first halves, one-shot validation on
untouched second halves. Definitions and pick rule preregistered in the spec.
"""
import numpy as np
import pandas as pd
import MetaTrader5 as mt5
from hedge_engine import simulate

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
R1 = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_M1, 0, 80000)
R5 = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_M5, 0, 80000)
R15 = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_M15, 0, 80000)
mt5.shutdown()

ANCH = range(6)


# ---- mask builders (only bars <= j are ever used) -------------------------

def pivots(h, l, k):
    """strict k-bar fractals: unique extreme in the 2k+1 window"""
    N = len(h)
    ph = np.zeros(N, bool)
    pl = np.zeros(N, bool)
    for i in range(k, N - k):
        wh = h[i - k:i + k + 1]
        if h[i] == wh.max() and (wh == h[i]).sum() == 1:
            ph[i] = True
        wl = l[i - k:i + k + 1]
        if l[i] == wl.min() and (wl == l[i]).sum() == 1:
            pl[i] = True
    return ph, pl


def last2(pivot_mask, values, k, rising):
    """mask[j] = the last two pivots CONFIRMED by bar j (pivot i is known only
    from bar i+k) are ascending/descending"""
    N = len(values)
    out = np.zeros(N, bool)
    v0 = v1 = None                      # v1 = most recent confirmed pivot
    for j in range(N):
        i = j - k
        if i >= 0 and pivot_mask[i]:
            v0, v1 = v1, values[i]
        if v0 is not None:
            out[j] = (v1 > v0) if rising else (v1 < v0)
    return out


def masks_for(R):
    h = R["high"].astype(float)
    l = R["low"].astype(float)
    ph1, pl1 = pivots(h, l, 1)
    ph2, pl2 = pivots(h, l, 2)
    d2b = last2(ph1, h, 1, True);  d2s = last2(pl1, l, 1, False)
    d3b = last2(pl1, l, 1, True);  d3s = last2(ph1, h, 1, False)
    d4b = last2(pl2, l, 2, True);  d4s = last2(ph2, h, 2, False)
    hs = pd.Series(h).rolling(10).max().values
    ls = pd.Series(l).rolling(10).min().values
    d6b = h >= np.where(np.isnan(hs), np.inf, hs)
    d6s = l <= np.where(np.isnan(ls), -np.inf, ls)
    return {
        "D2 pivHH k1": (d2b, d2s),
        "D3 pivHL k1": (d3b, d3s),
        "D4 pivHL k2": (d4b, d4s),
        "D5 trend k1": (d2b & d3b, d2s & d3s),
        "D6 donch10":  (d6b, d6s),
    }


# ---- harness --------------------------------------------------------------

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


TFS = (("M1", R1), ("M5", R5), ("M15", R15))

print("=" * 96)
print("SELECTION - first halves, 6 anchors, R = rate-matched random seed 0")
print("=" * 96)
sel = {}          # def -> tf -> dict
shares = {}       # def -> tf -> share
for name, R in TFS:
    Rh = R[:len(R) // 2]
    months = (Rh["time"][-1] - Rh["time"][0]) / (86400 * 30.44)
    print(f"--- {name} first half ({months:.1f} months) ---")
    M = masks_for(Rh)
    rs0 = run6(Rh)
    eq0 = eqv(rs0)
    op0 = np.mean([r["opened"] for r in rs0])
    print(f"  {'A0':<12} mean {eq0.mean():9.2f}  dead {sum(r['dead'] for r in rs0)}/6  cycles {op0:6.0f}")
    for dname, (mb, ms) in M.items():
        rsF = run6(Rh, entry_filter=("mask", mb, ms))
        eqF = eqv(rsF)
        seen = sum(r["f_seen"] for r in rsF)
        passed = sum(r["f_pass"] for r in rsF)
        share = passed / seen if seen else float("nan")
        opF = np.mean([r["opened"] for r in rsF])
        if opF == op0:
            print(f"  {dname:<12} *** INERT - same cycles as A0, gate never fired ***")
        rsR = run6(Rh, entry_filter=("random", share), filter_seed=0)
        eqR = eqv(rsR)
        mA, sA, bA = stats(eqF, eq0)
        mR, sR, bR = stats(eqF, eqR)
        sel.setdefault(dname, {})[name] = dict(dA0=mA, dR=mR)
        shares.setdefault(dname, {})[name] = share
        print(f"  {dname:<12} mean {eqF.mean():9.2f}  dead {sum(r['dead'] for r in rsF)}/6  "
              f"cycles {opF:6.0f}  share {share:5.1%}  "
              f"vs A0 {mA:+8.2f} ({bA}/6)  vs R {mR:+8.2f} ({bR}/6)")
    print()

# pick rule: qualify = (F-R) mean > 0 on >=2 of 3 halves; pick largest sum(F-A0)
qual = [d for d in sel if sum(1 for tf in sel[d] if sel[d][tf]["dR"] > 0) >= 2]
print(f"qualifiers (F-R > 0 on >=2 of 3 halves): {qual or 'NONE'}")
if not qual:
    print("NO QUALIFIER - SPEC CLOSES, no validation run.")
    raise SystemExit(0)
scores = {d: sum(sel[d][tf]["dA0"] for tf in sel[d]) for d in qual}
best = max(scores.values())
picked = next(d for d in ("D2 pivHH k1", "D3 pivHL k1", "D4 pivHL k2",
                          "D5 trend k1", "D6 donch10")
              if d in qual and scores[d] == best)
print(f"PICKED: {picked}  (sum F-A0 across halves {scores[picked]:+.2f}; "
      f"all scores {dict((k, round(v, 1)) for k, v in scores.items())})")

print()
print("=" * 96)
print("VALIDATION - untouched second halves. One shot.")
print("=" * 96)
res = {}
for name, R in TFS:
    Rh = R[len(R) // 2:]
    months = (Rh["time"][-1] - Rh["time"][0]) / (86400 * 30.44)
    print(f"--- {name} second half ({months:.1f} months) ---")
    mb, ms = masks_for(Rh)[picked]
    rs0 = run6(Rh)
    eq0 = eqv(rs0)
    print(f"  {'A0':<12} mean {eq0.mean():9.2f}  dead {sum(r['dead'] for r in rs0)}/6")
    rsF = run6(Rh, entry_filter=("mask", mb, ms))
    eqF = eqv(rsF)
    seen = sum(r["f_seen"] for r in rsF)
    passed = sum(r["f_pass"] for r in rsF)
    share = passed / seen if seen else float("nan")
    eqR = np.mean([eqv(run6(Rh, entry_filter=("random", share), filter_seed=s))
                   for s in (0, 1, 2)], axis=0)
    mA, sA, bA = stats(eqF, eq0)
    mR, sR, bR = stats(eqF, eqR)
    print(f"  {'F ' + picked:<12} mean {eqF.mean():9.2f}  dead {sum(r['dead'] for r in rsF)}/6  "
          f"share {share:5.1%}")
    print(f"  vs A0 {mA:+9.2f}  2SE {sA:7.2f}  better {bA}/6")
    print(f"  vs R  {mR:+9.2f}  2SE {sR:7.2f}  better {bR}/6")
    res[name] = dict(share=share,
                     beats_a0=(mA > sA and bA >= 5), loses_a0=(mA < -sA),
                     beats_r=(mR > sR and bR >= 5), loses_r=(mR < -sR))
    print()

print("=" * 96)
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
