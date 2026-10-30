"""bos_rise_be.py (2026-10-30, owner: "move SL to breakeven half way to TP for that minimum rise target")
Small fixed targets after each BOS break, stop moved to entry once price is halfway to the target (fastbt, one trade
at a time, stop-first inside a bar). Compared with the same without breakeven and with 30 random-direction replays."""
import os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fastbt as F, signals as S

for tf, k in ((5, 3), (15, 2), (60, 2)):
    base = S.bos(tf=tf, k=k)
    print("\nBOS M%d" % tf)
    for tgt in (20, 50, 100, 200):
        sig = [(i, d, sd, float(tgt)) for (i, d, sd, _) in base]
        for be in (0.0, 0.5):
            tr = F.simulate(sig, be_frac=be)
            r = F.report(tr, "", quiet=True)
            why = {w: sum(x["why"] == w for x in tr) for w in ("tp", "be", "sl", "time")}
            nul = [F.report(F.simulate(S.random_like(sig, seed=s), be_frac=be), "", quiet=True)["net"] for s in range(30)]
            print("  target %3d pts  BE %s: %5d trades  TP %5d  BE-out %5d  stop %4d | net %+7.0f$  months+ %d/10 | random %+6.0f$ (sd %.0f)" % (
                tgt, "half" if be else "off ", r["n"], why["tp"], why["be"], why["sl"], r["net"], r["months_up"], np.mean(nul), np.std(nul)), flush=True)
