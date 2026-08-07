"""PHASE 0 of SPEC_ADAPTIVE_SPACING - the cost gate. No P&L anywhere here.

Questions answered, in order:
  1. What do ATR(14) and the adaptive unit S_t actually look like per timeframe?
  2. What add distances does the CURRENT rule (A0) produce? (A3's k is
     mean-matched to their median, so this comes first.)
  3. Subset check: can A3 ever accept an add that A0 would not? (Must be NO.)
  4. What share of A0's adds would A3 reject, and are the rejected ones the
     close-clustered ones (the point) or everything (rate-matching in disguise)?
  5. Informational: the Jensen penalty on A1/A2 - scaling a distance the spread
     is paid against RAISES expected cost share even at the same mean, because
     E[1/S] > 1/E[S]. Quantified, not guessed.

AMENDMENTS to the spec, made BEFORE this ran (no results existed):
  a. The Phase-0 gate metric in section 4 was internally inconsistent - the
     "20 x spread" threshold (200 pts) exceeds the clamp ceiling (100 pts), so
     EVERY add in EVERY arm would read "sub-cost". Replaced by the enforceable
     form: A3 must not create any trigger the fixed rule would not have taken
     (subset property), and its S_t floor must keep spread <= 40% of spacing.
  b. ATR is computed on the RUN's own timeframe (M1 data only reaches back ~55
     days, so "M1 ATR" cannot exist for the 27-month M15 stretch). k is
     mean-matched per timeframe from the ATR series alone - never from P&L -
     and then frozen across anchors.
"""
import numpy as np
import MetaTrader5 as mt5
from hedge_engine import simulate

SPREAD = 10.0          # price units; $0.10 per 0.01 lot per position

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
TFS = (("M1", mt5.TIMEFRAME_M1, 60), ("M5", mt5.TIMEFRAME_M5, 300),
       ("M15", mt5.TIMEFRAME_M15, 900))
DATA = {n: (mt5.copy_rates_from_pos("BTCUSDm", tf, 0, 80000), secs)
        for n, tf, secs in TFS}
mt5.shutdown()


def atr14(R):
    h, l, c = R["high"].astype(float), R["low"].astype(float), R["close"].astype(float)
    pc = np.concatenate([[c[0]], c[:-1]])
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    a = np.full(len(tr), np.nan)
    a[13] = tr[:14].mean()
    for i in range(14, len(tr)):
        a[i] = (a[i - 1] * 13 + tr[i]) / 14.0        # Wilder smoothing
    return a


def calibrate(atr, target, lo, hi, iters=60):
    """k such that mean(clamp(k*atr, lo, hi)) == target, from the ATR series
    alone. Iterative because the clamp makes it non-linear."""
    v = atr[~np.isnan(atr)]
    k = target / v.mean()
    for _ in range(iters):
        m = np.clip(k * v, lo, hi).mean()
        if abs(m - target) < 1e-6:
            break
        k *= target / m
    return k, np.clip(k * v, lo, hi)


def add_distances(R, a):
    """Every A0 recovery add: its distance to the NEAREST open basket entry at
    fill time, plus the bar index of the fill (for ATR sampling)."""
    r = simulate(R, a=a, arm="same")
    assert r["ok"]
    tl = r["tlog"]
    out = []
    for i, t in enumerate(tl):
        if t["kind"] == "first":
            continue
        # basket members open when this add filled
        open_px = [u["px"] for u in tl
                   if u is not t and u["tin"] <= t["tin"]
                   and (u["tout"] is None or u["tout"] is None or u["tout"] > t["tin"] or u["tout"] == 0)]
        if not open_px:
            continue
        d = min(abs(t["px"] - p) for p in open_px)
        out.append((t["tin"], d))
    return out


print("=" * 88)
print("PHASE 0 - COST GATE   (distributions only, no equity curves)")
print("=" * 88)

verdicts = {}
for name in ("M1", "M5", "M15"):
    R, secs = DATA[name]
    tm = R["time"].astype(np.int64)
    a = atr14(R)
    v = a[~np.isnan(a)]
    months = (tm[-1] - tm[0]) / (86400 * 30.44)

    # ---- 1. ATR itself -----------------------------------------------------
    print(f"\n--- {name}  ({months:.1f} months, {len(R)} bars) ---")
    print(f"ATR14: mean {v.mean():7.1f}  median {np.median(v):7.1f}  "
          f"p10 {np.percentile(v,10):6.1f}  p90 {np.percentile(v,90):7.1f}")

    # ---- 2. A0 add distances (6 anchors pooled) ----------------------------
    dists, s_at_add = [], []
    for anc in range(6):
        for tin, d in add_distances(R, anc):
            j = np.searchsorted(tm, tin, side="right") - 2   # last CLOSED bar
            if 13 < j < len(a) and not np.isnan(a[j]):
                dists.append(d)
                s_at_add.append(a[j])
    dists = np.array(dists); s_at_add = np.array(s_at_add)
    med_d = float(np.median(dists))
    print(f"A0 adds (6 anchors pooled): n={len(dists)}  "
          f"distance median {med_d:6.1f}  p25 {np.percentile(dists,25):6.1f}  "
          f"p75 {np.percentile(dists,75):7.1f}  p10 {np.percentile(dists,10):6.1f}")

    # ---- 3. calibrate A3's unit to the median add distance ------------------
    lo, hi = max(25.0, med_d / 2), med_d * 2
    k3, s3 = calibrate(a, med_d, lo, hi)
    print(f"A3 unit: k={k3:.2f}  clamp [{lo:.0f},{hi:.0f}]  "
          f"mean S {s3.mean():6.1f} (target {med_d:.1f})  "
          f"S p10 {np.percentile(s3,10):6.1f}  p90 {np.percentile(s3,90):7.1f}")

    # spread as a share of the SPACING floor (worst case) and typical
    worst_share = SPREAD / lo * 100
    print(f"spread vs spacing: worst {worst_share:.0f}% (at clamp floor)  "
          f"typical {SPREAD/np.median(s3)*100:.0f}%   [gate limit 40%]")

    # ---- 4. what would A3 reject? ------------------------------------------
    s_here = np.clip(k3 * s_at_add, lo, hi)
    rej = dists < s_here
    print(f"A3 would reject {rej.sum()}/{len(dists)} of A0's adds "
          f"({100*rej.mean():.0f}%)")
    if rej.any() and (~rej).any():
        print(f"   rejected ones: median distance {np.median(dists[rej]):6.1f}  "
              f"kept ones: median {np.median(dists[~rej]):6.1f}")

    # ---- 5. Jensen penalty for A1 / A2 (informational) ----------------------
    kT, sT = calibrate(a, 250.0, 125.0, 500.0)      # TP knob
    jen_tp = (SPREAD / sT).mean() / (SPREAD / 250.0) - 1
    kG, sG = calibrate(a, 150.0, 75.0, 300.0)       # trigger knob
    jen_tr = (SPREAD / sG).mean() / (SPREAD / 150.0) - 1
    print(f"Jensen cost penalty at equal means: TP {jen_tp*100:+.1f}%   "
          f"trigger {jen_tr*100:+.1f}%")

    # ---- gate ---------------------------------------------------------------
    # A3 only REJECTS adds (subset property holds by construction: the renko
    # reversal trigger is untouched). Fail conditions:
    #   - spread share at the clamp floor exceeds 40%
    #   - A3 rejects so much (>80%) that it is just "fewer adds" in disguise
    ok = worst_share <= 40.0 and rej.mean() <= 0.80
    verdicts[name] = (ok, worst_share, 100 * rej.mean())
    print(f"GATE {name}: {'PASS' if ok else 'FAIL'}")

print("\n" + "=" * 88)
print("PHASE 0 VERDICT")
for n, (ok, w, r) in verdicts.items():
    print(f"  {n:4s} {'PASS' if ok else 'FAIL'}   spread@floor {w:.0f}%   rejects {r:.0f}%")
print("A3 subset property: holds by construction (renko trigger untouched; "
      "A3 only rejects).")
print("A1/A2 note: the Jensen penalty above is the BUILT-IN extra cost of "
      "scaling those knobs;\nif Phase 2 shows either arm winning by less than "
      "its penalty, the win is not real.")
