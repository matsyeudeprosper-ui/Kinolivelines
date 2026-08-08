"""SPEC_HHLL_RENKO - the user's renko-brick HH/HL definition, as definition #6
after SPEC_HHLL_VARIANTS killed D2-D6.

DEFINITION (preregistered before any run):
  Bricks: built from bar CLOSES exactly like hedge_engine (brick 50, rev 2,
  seeded at the slice's first OPEN) - one renko walk per anchor, so the
  anchor sweep also captures renko seed sensitivity (the $240 noise-floor
  lesson).
  Swing high = the last brick close of an up-run, confirmed the moment the
  first down-reversal brick prints. Swing low = mirror.
  buy[j]  = >=2 swing highs and >=2 swing lows confirmed by bar j, AND
            last swing high > previous AND last swing low > previous
  sell[j] = mirror (lower lows AND lower highs). Equal swings = neither.
  Gate applies to NEW CYCLES only, arm="same" (the live harvest shape).

PROTOCOL (same as SPEC_HHLL_VARIANTS):
  Qualification on FIRST halves of M1/M5/M15: (F-R) mean > 0 on >=2 of 3,
  R = rate-matched random seed 0. Fail -> spec closes, second halves stay
  untouched. Pass -> one-shot validation on second halves, R averaged over
  seeds 0,1,2. Survive = beats A0 AND R on >=2 TFs (mean>2SE, >=5/6), no
  >2SE loss anywhere, share 20-80% somewhere.
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
BRICK, REV = 50.0, 2


def renko_masks(R, brick=BRICK, rev=REV):
    """Replicates hedge_engine's brick walk (lines 125, 199-207) and tags each
    bar with the HH/HL / LL/LH state of the CONFIRMED swings so far."""
    o = R["open"].astype(float)
    c = R["close"].astype(float)
    N = len(c)
    buy = np.zeros(N, bool)
    sell = np.zeros(N, bool)
    ao = ac = float(o[0])
    d = 0
    sh, sl_ = [], []
    for j in range(N):
        ci = c[j]
        while True:
            u = (ao if d == -1 else ac) + brick * (rev if d == -1 else 1)
            n_ = (ao if d == 1 else ac) - brick * (rev if d == 1 else 1)
            if ci >= u:
                if d == -1:
                    sl_.append(ac)      # ac = lowest close of the down-run
                base = ao if d == -1 else ac
                ao, ac, d = base, base + brick, 1
            elif ci <= n_:
                if d == 1:
                    sh.append(ac)       # ac = highest close of the up-run
                base = ao if d == 1 else ac
                ao, ac, d = base, base - brick, -1
            else:
                break
        if len(sh) >= 2 and len(sl_) >= 2:
            buy[j] = sh[-1] > sh[-2] and sl_[-1] > sl_[-2]
            sell[j] = sh[-1] < sh[-2] and sl_[-1] < sl_[-2]
    return buy, sell


def mask_for_anchor(Rh, a):
    """per-anchor renko walk; front-pad so the engine's [a:] slice aligns"""
    mb, ms = renko_masks(Rh[a:])
    pad = np.zeros(a, bool)
    return np.concatenate([pad, mb]), np.concatenate([pad, ms])


def run6_filtered(Rh):
    rs = []
    for a in ANCH:
        mb, ms = mask_for_anchor(Rh, a)
        r = simulate(Rh, a=a, arm="same", entry_filter=("mask", mb, ms))
        assert r["ok"], f"invariant failed anchor {a}"
        rs.append(r)
    return rs


def run6(Rh, **kw):
    rs = []
    for a in ANCH:
        r = simulate(Rh, a=a, arm="same", **kw)
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
print("QUALIFICATION - first halves, 6 anchors (renko re-seeded per anchor)")
print("=" * 96)
qual_hits = 0
for name, R in TFS:
    Rh = R[:len(R) // 2]
    months = (Rh["time"][-1] - Rh["time"][0]) / (86400 * 30.44)
    print(f"--- {name} first half ({months:.1f} months) ---")
    rs0 = run6(Rh)
    eq0 = eqv(rs0)
    op0 = np.mean([r["opened"] for r in rs0])
    print(f"  {'A0':<10} mean {eq0.mean():9.2f}  dead {sum(r['dead'] for r in rs0)}/6  cycles {op0:6.0f}")
    rsF = run6_filtered(Rh)
    eqF = eqv(rsF)
    seen = sum(r["f_seen"] for r in rsF)
    passed = sum(r["f_pass"] for r in rsF)
    share = passed / seen if seen else float("nan")
    opF = np.mean([r["opened"] for r in rsF])
    if opF == op0:
        print(f"  {'RENKO':<10} *** INERT - same cycles as A0, gate never fired ***")
    rsR = run6(Rh, entry_filter=("random", share), filter_seed=0)
    eqR = eqv(rsR)
    mA, sA, bA = stats(eqF, eq0)
    mR, sR, bR = stats(eqF, eqR)
    if mR > 0:
        qual_hits += 1
    print(f"  {'RENKO':<10} mean {eqF.mean():9.2f}  dead {sum(r['dead'] for r in rsF)}/6  "
          f"cycles {opF:6.0f}  share {share:5.1%}  "
          f"vs A0 {mA:+8.2f} 2SE {sA:6.2f} ({bA}/6)  vs R {mR:+8.2f} 2SE {sR:6.2f} ({bR}/6)")
    print()

print(f"qualification: (F-R) > 0 on {qual_hits}/3 first halves (need >=2)")
if qual_hits < 2:
    print("NO QUALIFICATION - SPEC CLOSES, second halves stay untouched.")
    raise SystemExit(0)

print()
print("=" * 96)
print("VALIDATION - untouched second halves. One shot.")
print("=" * 96)
res = {}
for name, R in TFS:
    Rh = R[len(R) // 2:]
    months = (Rh["time"][-1] - Rh["time"][0]) / (86400 * 30.44)
    print(f"--- {name} second half ({months:.1f} months) ---")
    rs0 = run6(Rh)
    eq0 = eqv(rs0)
    print(f"  {'A0':<10} mean {eq0.mean():9.2f}  dead {sum(r['dead'] for r in rs0)}/6")
    rsF = run6_filtered(Rh)
    eqF = eqv(rsF)
    seen = sum(r["f_seen"] for r in rsF)
    passed = sum(r["f_pass"] for r in rsF)
    share = passed / seen if seen else float("nan")
    eqR = np.mean([eqv(run6(Rh, entry_filter=("random", share), filter_seed=s))
                   for s in (0, 1, 2)], axis=0)
    mA, sA, bA = stats(eqF, eq0)
    mR, sR, bR = stats(eqF, eqR)
    print(f"  {'RENKO':<10} mean {eqF.mean():9.2f}  dead {sum(r['dead'] for r in rsF)}/6  share {share:5.1%}")
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
