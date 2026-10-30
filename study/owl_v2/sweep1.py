"""sweep1.py - first landscape: BOS family across frames, follow vs fade, plus the random-direction control."""
import itertools, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fastbt as F, signals as S

rows = []
t0 = time.time()
for tf, k, rr, mode in itertools.product([1, 5, 15, 60], [2, 3, 5], [0.8, 1.0, 1.5, 2.0], ["follow", "fade"]):
    sig = S.bos(tf=tf, k=k, rr=rr, mode=mode)
    tr = F.simulate(sig)
    r = F.report(tr, "bos tf%d k%d rr%.1f %s" % (tf, k, rr, mode))
    rc = F.report(F.simulate(S.random_like(sig)), "   random dir", quiet=True)
    print("      random-dir net %+.2f  m+ %d" % (rc["net"], rc["months_up"]))
    r["rand_net"] = rc["net"]
    rows.append(r)
json.dump(rows, default=float, fp=open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "sweep1.json"), "w"), indent=1)
print("done %.0fs" % (time.time() - t0))
