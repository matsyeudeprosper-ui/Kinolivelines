"""bos_rise_split.py (2026-10-31, owner: "run it") - split check of the BOS M60 small-target result from bos_rise_be.py.
Pick the best target/breakeven on Jan-May, judge it on Jun-Oct (and the reverse), each half against 60 random-direction
replays of the same signals. Also the spread paid per half (the Jun-Oct spread fall could explain a gain)."""
import os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fastbt as F, signals as S

SEEDS = 60
base = S.bos(tf=60, k=2)
rows = []
for tgt in (20, 50, 100, 200):
    sig = [(i, d, sd, float(tgt)) for (i, d, sd, _) in base]
    for be in (0.0, 0.5):
        tr = F.simulate(sig, be_frac=be)
        r = F.report(tr, "", quiet=True)
        nul = [F.report(F.simulate(S.random_like(sig, seed=s), be_frac=be), "", quiet=True) for s in range(SEEDS)]
        n1 = np.array([x["h1"] for x in nul]); n2 = np.array([x["h2"] for x in nul])
        p1 = float(np.mean(n1 >= r["h1"])); p2 = float(np.mean(n2 >= r["h2"]))
        sp1 = np.mean([x["sp"] for x in tr if x["t"] < 1780272000]) if tr else 0  # before 2026-06-01 UTC
        sp2 = np.mean([x["sp"] for x in tr if x["t"] >= 1780272000]) if tr else 0
        name = "tgt %3d BE %s" % (tgt, "half" if be else "off ")
        rows.append((name, r, p1, p2))
        print("%s | Jan-May %+6.0f$ (random %+5.0f, chance %.2f) | Jun-Oct %+6.0f$ (random %+5.0f, chance %.2f) | spread %.0f -> %.0f | months %s" % (
            name, r["h1"], n1.mean(), p1, r["h2"], n2.mean(), p2, sp1, sp2, " ".join("%+.0f" % v for v in r["months"].values())), flush=True)

b1 = max(rows, key=lambda x: x[1]["h1"]); b2 = max(rows, key=lambda x: x[1]["h2"])
print("\nPICK ON Jan-May: %s -> judged Jun-Oct %+.0f$, chance %.2f" % (b1[0], b1[1]["h2"], b1[3]))
print("PICK ON Jun-Oct: %s -> judged Jan-May %+.0f$, chance %.2f" % (b2[0], b2[1]["h1"], b2[2]))
print("DONE")
