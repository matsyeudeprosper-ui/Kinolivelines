"""Controls for the FVG filter - the ones that killed three findings on
2026-09-17 when they were skipped.

fvg_test.py found: BOS whose confirming move left a raw FVG = +0.108
R/trade, 64.4%, 6/6 anchors; without = -0.050, 0/6. Before that is
repeated to anyone:

  1. HALVES      first half vs second half of the 41.7 days, separately
  2. SHUFFLE     re-deal the FVG tag at random across the same trades,
                 2000 times; where does the real subset mean fall?
  3. DIRECTION   buys vs sells - a one-sided filter is drift, not edge
  4. GATE ON     the live configuration (nervosity brake on)
  5. SPREAD      0 / 7 / 15 points

    python review/fvg_controls.py
"""
import datetime as dt
import os
import random
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.argv = ["fvg_controls"]

import fvg_test as T                   # noqa: E402  (replay, bars, gap)
import structure_bos_bot as B          # noqa: E402
import bisect                          # noqa: E402


def replay_full(R, spread, nerv_gate):
    """fvg_test.replay plus entry time and direction, optional brake."""
    eng = B.Struct()
    eng.quiet = True
    rng = [float(r["high"]) - float(r["low"]) for r in R]
    flips, marks, trades = [], [], []
    prev_trend = 0
    used_hi = used_lo = None
    pos = None
    lot, balance, rr = 0.02, 230.0, 0.8
    for i, bar in enumerate(R):
        t = int(bar["time"])
        o, h, l, c = (float(bar["open"]), float(bar["high"]),
                      float(bar["low"]), float(bar["close"]))
        if pos:
            d, e, sl, tp, oi, tag = pos
            hit_sl = (l <= sl) if d == 1 else (h >= sl)
            hit_tp = (h >= tp) if d == 1 else (l <= tp)
            if hit_sl or hit_tp:
                risk = abs(e - sl)
                win = bool(hit_tp and not hit_sl)
                pts = ((tp - e) * d - spread) if win else -(risk + spread)
                trades.append(dict(R=pts / risk, win=win, usd=pts * lot,
                                   d=d, t=tag["t"], g=tag["g"]))
                pos = None
        sig = eng.step(t, o, h, l, c)
        hv, lv = eng.hi_v, eng.lo_v
        if eng.trend != prev_trend and eng.trend != 0:
            flips.append(t)
            prev_trend = eng.trend
        if sig is not None:
            marks.append(t)
        if sig is None:
            continue
        if not any(f > t - B.AWAKE_WIN for f in flips):
            continue
        d, slp = sig
        flip = bool(flips) and flips[-1] == t
        lvl = hv if d == 1 else lv
        if not flip:
            if (d == 1 and used_hi == lvl) or (d == -1 and used_lo == lvl):
                continue
            if d == 1:
                used_hi = lvl
            else:
                used_lo = lvl
        if i >= 1440:
            mv2 = (bisect.bisect_left(marks, t)
                   - bisect.bisect_left(marks, t - 7200))
            if mv2 < 1:
                continue
            if nerv_gate:
                nv = (sorted(rng[i - 60:i])[30]
                      / max(sorted(rng[i - 1440:i])[720], 1e-9))
                if nv > 1.0:
                    continue
        if pos:
            continue
        risk = abs(c - slp)
        if risk <= B.S_MIN_DIST or risk * lot > B.MAX_RISK_PCT * balance:
            continue
        g = T.gap(R[i - 2], R[i], d) if i >= 2 else 0.0
        pos = (d, c, slp, c + d * rr * risk, i, dict(t=t, g=g))
    return trades


def mean_R(tr):
    return sum(x["R"] for x in tr) / len(tr) if tr else 0.0


def line(lab, tr):
    w = 100 * sum(1 for x in tr if x["win"]) / len(tr) if tr else 0
    return f"  {lab:<40}{len(tr):>5}{w:>8.1f}%{mean_R(tr):>+9.3f}"


def main():
    sym, R = T.bars()
    print(f"  {sym}  {len(R)/1440:.1f} jours\n")
    tr = replay_full(R, 7.0, nerv_gate=False)
    yes = [x for x in tr if x["g"] > 0]
    no = [x for x in tr if x["g"] <= 0]
    print(f"  {'':40}{'n':>5}{'reussite':>9}{'R/trade':>9}")
    print(line("reference: avec FVG", yes))
    print(line("reference: sans FVG", no))

    # 1. halves
    mid = sorted(x["t"] for x in tr)[len(tr) // 2]
    print("\n  1. LES DEUX MOITIES")
    for lab, f in (("1re moitie", lambda x: x["t"] < mid),
                   ("2e moitie", lambda x: x["t"] >= mid)):
        h = [x for x in tr if f(x)]
        hy = [x for x in h if x["g"] > 0]
        hn = [x for x in h if x["g"] <= 0]
        print(line(f"  {lab} avec FVG", hy))
        print(line(f"  {lab} sans FVG", hn))

    # 2. shuffle
    print("\n  2. MELANGE ALEATOIRE de l'etiquette (2000 fois)")
    Rs = [x["R"] for x in tr]
    k = len(yes)
    real = mean_R(yes)
    random.seed(7)
    sims = []
    for _ in range(2000):
        random.shuffle(Rs)
        sims.append(sum(Rs[:k]) / k)
    above = sum(1 for s in sims if s >= real)
    print(f"    reel {real:+.3f} | melanges: moyenne {st.mean(sims):+.3f}, "
          f"ecart-type {st.pstdev(sims):.3f}")
    print(f"    melanges >= reel : {above}/2000  ->  p = {above/2000:.4f}")
    print(f"    le reel est a {(real-st.mean(sims))/max(st.pstdev(sims),1e-9):+.1f} "
          f"ecarts-types du hasard")

    # 3. direction
    print("\n  3. ACHATS / VENTES")
    for lab, d in (("achats", 1), ("ventes", -1)):
        print(line(f"  {lab} avec FVG", [x for x in yes if x["d"] == d]))
        print(line(f"  {lab} sans FVG", [x for x in no if x["d"] == d]))

    # 4. live config
    print("\n  4. FREIN NERVOSITE ACTIVE (config Valere)")
    trg = replay_full(R, 7.0, nerv_gate=True)
    print(line("  avec FVG", [x for x in trg if x["g"] > 0]))
    print(line("  sans FVG", [x for x in trg if x["g"] <= 0]))

    # 5. spread
    print("\n  5. SPREAD")
    for sp in (0.0, 7.0, 15.0):
        t2 = replay_full(R, sp, nerv_gate=False)
        y2 = [x for x in t2 if x["g"] > 0]
        n2 = [x for x in t2 if x["g"] <= 0]
        print(f"    spread {sp:>4.0f} : avec {mean_R(y2):+.3f} ({len(y2)})"
              f"   sans {mean_R(n2):+.3f} ({len(n2)})   ecart {mean_R(y2)-mean_R(n2):+.3f}")


if __name__ == "__main__":
    main()
