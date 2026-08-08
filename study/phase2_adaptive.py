"""PHASE 2 of SPEC_ADAPTIVE_SPACING. Everything preregistered; k frozen.

Arms per timeframe, 6 paired anchors each:
  A0  the live rule
  A1  adaptive recovery trigger  (mean-matched to 150, clamp [75,300])
  A2  adaptive TP                (mean-matched to 250, clamp [125,500])
  A3  adaptive min add distance  (k FROZEN from Phase 0: 3.64/1.84/1.58)
Controls:
  RM  rate-matched fixed min add distance (D bisected to match A3's add count
      within 5% on the stretch, then frozen across its anchors)
  SH  shuffled-ATR A3 (day-blocks permuted, seeds 0/1/2) - runs for every tf,
      cheap enough, and the spec only NEEDS it for a survivor.

Survival (spec section 5): M15 >=5/6 better AND mean > 2SE AND > noise floor;
not losing >2SE on M1/M5; beats RM on >=4/6; SH reproduces < half the gain.
"""
import numpy as np
import MetaTrader5 as mt5
from hedge_engine import simulate

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
TFS = (("M1", mt5.TIMEFRAME_M1), ("M5", mt5.TIMEFRAME_M5), ("M15", mt5.TIMEFRAME_M15))
DATA = {n: mt5.copy_rates_from_pos("BTCUSDm", tf, 0, 80000) for n, tf in TFS}
mt5.shutdown()

K3 = {"M1": (3.64, 70.0, 280.0), "M5": (1.84, 126.3, 505.4), "M15": (1.58, 214.9, 859.6)}
ANCH = range(6)


def wilder14(R):
    h, l, c = R["high"].astype(float), R["low"].astype(float), R["close"].astype(float)
    pc = np.concatenate([[c[0]], c[:-1]])
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    a = np.full(len(tr), np.nan)
    a[13] = tr[:14].mean()
    for i in range(14, len(tr)):
        a[i] = (a[i - 1] * 13 + tr[i]) / 14.0
    return a


def calibrate(atr, target, lo, hi):
    v = atr[~np.isnan(atr)]
    k = target / v.mean()
    for _ in range(60):
        m = np.clip(k * v, lo, hi).mean()
        if abs(m - target) < 1e-6:
            break
        k *= target / m
    return k


def run(R, adapt=None, atr_override=None):
    out = []
    for a in ANCH:
        r = simulate(R, a=a, arm="same", adapt=adapt, atr_override=atr_override)
        assert r["ok"], "invariant failed"
        out.append(r)
    return out


def row(label, rs, base_eq):
    eq = np.array([r["eq"] for r in rs])
    adds = np.mean([r["hedges"] for r in rs])
    dead = sum(1 for r in rs if r["dead"])
    mdd = np.mean([r["mdd"] for r in rs])
    if base_eq is None:
        print(f"{label:<22}{eq.mean():>10.2f}{'':>10}{'':>8}{'-':>8}{dead:>5}/6"
              f"{adds:>9.0f}{mdd:>10.2f}")
    else:
        d = eq - base_eq
        se2 = 2 * d.std(ddof=1) / np.sqrt(len(d))
        print(f"{label:<22}{eq.mean():>10.2f}{d.mean():>+10.2f}{se2:>8.2f}"
              f"{(d > 0).sum():>7}/6{dead:>5}/6{adds:>9.0f}{mdd:>10.2f}")
        print(f"{'':<22}per anchor: " + " ".join(f"{x:+9.2f}" for x in d))
    return eq


def day_shuffle_atr(R, atr, seed):
    """Permute whole-day ATR blocks over the bar sequence. Lengths differ, so
    the permuted day's values are stretched/truncated to fit - crude, but the
    point is only to break the link between TODAY's vol and TODAY's prices."""
    rng = np.random.default_rng(seed)
    day = (R["time"].astype(np.int64) // 86400)
    uniq = np.unique(day)
    perm = rng.permutation(len(uniq))
    out = np.empty_like(atr)
    for i, d in enumerate(uniq):
        m = day == d
        src = atr[day == uniq[perm[i]]]
        n = m.sum()
        if len(src) == 0:
            out[m] = atr[m]
        elif len(src) >= n:
            out[m] = src[:n]
        else:
            out[m] = np.concatenate([src, np.full(n - len(src), src[-1])])
    return out


verdict = {}
for name, _ in TFS:
    R = DATA[name]
    atr = wilder14(R)
    months = (R["time"][-1] - R["time"][0]) / (86400 * 30.44)
    k3, lo3, hi3 = K3[name]
    k1 = calibrate(atr, 150.0, 75.0, 300.0)
    k2 = calibrate(atr, 250.0, 125.0, 500.0)

    print("=" * 96)
    print(f"{name}  {months:.1f} months   k1(trig)={k1:.2f}  k2(tp)={k2:.2f}  "
          f"k3(add)={k3:.2f} [frozen from Phase 0]")
    print("=" * 96)
    print(f"{'arm':<22}{'mean end':>10}{'vs A0':>10}{'2SE':>8}{'better':>9}"
          f"{'dead':>7}{'adds':>9}{'maxDD':>10}")

    rs0 = run(R)
    eq0 = row("A0 live rule", rs0, None)
    noise = eq0.std(ddof=1)
    print(f"{'':<22}anchor noise floor (A0 std): {noise:.2f}")

    rs1 = run(R, adapt={"trigger": (k1, 75.0, 300.0)})
    row("A1 adaptive trigger", rs1, eq0)
    rs2 = run(R, adapt={"tp": (k2, 125.0, 500.0)})
    row("A2 adaptive TP", rs2, eq0)
    rs3 = run(R, adapt={"add_dist": (k3, lo3, hi3)})
    eq3 = row("A3 adaptive add-dist", rs3, eq0)

    # Trap-16: arms must actually differ from A0 in structure
    for lbl, rs in (("A1", rs1), ("A2", rs2), ("A3", rs3)):
        same = all(abs(x["eq"] - y["eq"]) < 0.005 for x, y in zip(rs, rs0))
        if same:
            print(f"*** {lbl} IDENTICAL TO A0 - DEAD GATE (Trap 16), result void ***")

    # ---- rate-matched control for A3 -----------------------------------
    target_adds = np.mean([r["hedges"] for r in rs3])
    lo_d, hi_d = 10.0, 2000.0
    for _ in range(18):
        mid = 0.5 * (lo_d + hi_d)
        r_ = simulate(R, a=0, arm="same", adapt={"add_dist": (0.0, mid, mid)})
        if r_["hedges"] > target_adds:
            lo_d = mid
        else:
            hi_d = mid
    D = 0.5 * (lo_d + hi_d)
    rsRM = run(R, adapt={"add_dist": (0.0, D, D)})
    eqRM = row(f"RM fixed dist {D:.0f}", rsRM, eq0)
    rm_adds = np.mean([r["hedges"] for r in rsRM])
    print(f"{'':<22}add-count match: A3 {target_adds:.0f} vs RM {rm_adds:.0f} "
          f"({'OK' if abs(rm_adds-target_adds) <= 0.05*target_adds else 'OUTSIDE 5% - note'})")

    # ---- shuffled-ATR control for A3 ------------------------------------
    sh_means = []
    for seed in (0, 1, 2):
        atr_sh = day_shuffle_atr(R, atr, seed)
        rsSH = run(R, adapt={"add_dist": (k3, lo3, hi3)}, atr_override=atr_sh)
        sh_means.append(np.mean([r["eq"] for r in rsSH]))
    print(f"{'SH shuffled-ATR A3':<22}{np.mean(sh_means):>10.2f}  "
          f"(seeds: {' '.join(f'{m:.0f}' for m in sh_means)})")

    d3 = eq3 - eq0
    verdict[name] = dict(
        a3_mean=float(d3.mean()), a3_se2=float(2 * d3.std(ddof=1) / np.sqrt(6)),
        a3_better=int((d3 > 0).sum()), noise=float(noise),
        rm_mean=float((eqRM - eq0).mean()),
        a3_vs_rm=int((eq3 - eqRM > 0).sum()),
        sh_gain=float(np.mean(sh_means) - eq0.mean()))
    print()

print("=" * 96)
print("PHASE 2 VERDICT (criteria from spec section 5, judged mechanically)")
v15, v5, v1 = verdict["M15"], verdict["M5"], verdict["M1"]
c1 = v15["a3_better"] >= 5 and v15["a3_mean"] > v15["a3_se2"] and v15["a3_mean"] > v15["noise"]
c2 = not (v1["a3_mean"] < -v1["a3_se2"]) and not (v5["a3_mean"] < -v5["a3_se2"])
c3 = v15["a3_vs_rm"] >= 4
c4 = v15["sh_gain"] < 0.5 * max(v15["a3_mean"], 1e-9)
print(f"  M15 better>=5/6 AND mean>2SE AND mean>noise : {c1}  "
      f"(better {v15['a3_better']}/6, mean {v15['a3_mean']:+.2f}, "
      f"2SE {v15['a3_se2']:.2f}, noise {v15['noise']:.2f})")
print(f"  no M1/M5 loss beyond 2SE                    : {c2}  "
      f"(M1 {v1['a3_mean']:+.2f}/2SE {v1['a3_se2']:.2f}, "
      f"M5 {v5['a3_mean']:+.2f}/2SE {v5['a3_se2']:.2f})")
print(f"  beats rate-matched on >=4/6 (M15)           : {c3}  "
      f"({v15['a3_vs_rm']}/6, RM itself {v15['rm_mean']:+.2f} vs A0)")
print(f"  shuffled ATR reproduces < half the gain     : {c4}  "
      f"(shuffle gain {v15['sh_gain']:+.2f})")
print(f"  A3 SURVIVES: {c1 and c2 and c3 and c4}")
