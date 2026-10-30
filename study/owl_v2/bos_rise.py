"""bos_rise.py (2026-10-30, owner: "what is the minimum distance rise from a BOS breakout, so I take that minimum each time")
For every BOS break (fastbt fills: entry next M1 open, buy pays the ask), how far price goes the break's way BEFORE the
structure stop is hit (max 24 h). Percentiles in points and in stop-widths; same for random directions (control).
Then: hit rate and money of "take a small target X each time" vs random."""
import os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fastbt as F, signals as S

M = F.m1()
h, l, o, sp = M["h"], M["l"], M["o"], M["sp"]


def rise(sig):
    out = []
    for i, d, sd, _ in sig:
        e = o[i] + (sp[i] if d == 1 else 0)
        H, L, SS = h[i:i + 1440], l[i:i + 1440], sp[i:i + 1440]
        fav = (H - e) if d == 1 else (e - (L + SS))
        adv = (e - L) if d == 1 else ((H + SS) - e)
        k = np.flatnonzero(adv >= sd)
        j = k[0] if len(k) else len(H)
        mf = fav[:j].max() if j > 0 else min(0.0, fav[0])     # the stop bar itself counts as nothing (stop first)
        out.append((max(mf, 0.0), sd))
    return np.array(out)


for tf, k in ((5, 3), (15, 2), (60, 2)):
    sig = S.bos(tf=tf, k=k)
    A, R = rise(sig), rise(S.random_like(sig, seed=3))
    print("\nBOS M%d (pivot %d): %d breaks, median stop %.0f pts" % (tf, k, len(A), np.median(A[:, 1])))
    for name, X in (("BOS ", A), ("rand", R)):
        print("  %s rise before stop, points: p5 %4.0f  p10 %4.0f  p25 %4.0f  p50 %5.0f  | breaks that never rose 20 pts: %4.1f%%" % (
            name, *np.percentile(X[:, 0], [5, 10, 25, 50]), 100 * np.mean(X[:, 0] < 20)))
    for tgt in (20, 50, 100, 0.25, 0.5):
        f = (lambda X: X[:, 0] >= (tgt if tgt >= 1 else tgt * X[:, 1]))
        w = lambda X: f(X).mean()
        usd = lambda X: np.where(f(X), (tgt if tgt >= 1 else tgt * X[:, 1]), -X[:, 1]).sum() * 0.01
        lab = ("%d pts" % tgt) if tgt >= 1 else ("%.2f x stop" % tgt)
        print("  target %-10s reached %5.1f%% (random %5.1f%%)   money %+8.0f$ (random %+8.0f$)" % (lab, 100 * w(A), 100 * w(R), usd(A), usd(R)))
